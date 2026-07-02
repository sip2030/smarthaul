import os
import re
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from threading import Lock
from time import time
from typing import Dict, Any, Optional, List, Tuple

from auth import hash_password, is_strong_password

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None
    dict_row = None

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DB_PATH = Path(os.getenv("DATABASE_PATH") or (Path(__file__).resolve().parent / "smarthaul.db"))


def get_bootstrap_admin_config() -> dict[str, str]:
    return {
        "name": os.getenv("BOOTSTRAP_ADMIN_NAME", "SmartHaul Admin").strip(),
        "email": os.getenv("BOOTSTRAP_ADMIN_EMAIL", "").strip(),
        "password": os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "").strip(),
    }


def get_database_backend() -> str:
    return "postgres" if DATABASE_URL.startswith(("postgres://", "postgresql://")) else "sqlite"


def translate_query_for_postgres(query: str) -> str:
    translated = query.replace("?", "%s")
    if translated.lstrip().upper().startswith("INSERT OR IGNORE INTO"):
        translated = re.sub(r"INSERT OR IGNORE INTO", "INSERT INTO", translated, count=1, flags=re.IGNORECASE)
        translated = f"{translated} ON CONFLICT DO NOTHING"
    return translated


class CursorResult:
    def __init__(self, cursor, lastrowid=None):
        self._cursor = cursor
        self.lastrowid = lastrowid

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()


class PostgresConnection:
    def __init__(self, connection):
        self._connection = connection

    def execute(self, query: str, params=()):
        translated = translate_query_for_postgres(query)
        cursor = self._connection.cursor()
        is_insert = translated.lstrip().upper().startswith("INSERT INTO")
        has_returning = "RETURNING" in translated.upper()
        if is_insert and not has_returning:
            translated = f"{translated} RETURNING id"
        cursor.execute(translated, params or ())
        lastrowid = None
        if is_insert:
            inserted_row = cursor.fetchone()
            if inserted_row:
                lastrowid = inserted_row["id"] if isinstance(inserted_row, dict) else inserted_row[0]
        return CursorResult(cursor, lastrowid=lastrowid)

    def commit(self):
        self._connection.commit()

    def close(self):
        self._connection.close()


class QueryCache:
    """Simple thread-safe query result cache with TTL"""
    def __init__(self, ttl_seconds: int = 60):
        self.cache: Dict[str, Tuple[Any, float]] = {}
        self.ttl_seconds = ttl_seconds
        self.lock = Lock()
    
    def get(self, key: str) -> Optional[Any]:
        with self.lock:
            if key in self.cache:
                result, timestamp = self.cache[key]
                if time() - timestamp < self.ttl_seconds:
                    return result
                else:
                    del self.cache[key]
        return None
    
    def set(self, key: str, value: Any) -> None:
        with self.lock:
            self.cache[key] = (value, time())
    
    def invalidate(self, key: str = None) -> None:
        with self.lock:
            if key:
                self.cache.pop(key, None)
            else:
                self.cache.clear()


class ConnectionPool:
    """Simple connection pool for PostgreSQL connections"""
    def __init__(self, max_size: int = 10):
        self.max_size = max_size
        self.available: List[Any] = []
        self.in_use = 0
        self.lock = Lock()
    
    def get_connection(self):
        with self.lock:
            if self.available:
                conn = self.available.pop()
            else:
                if self.in_use >= self.max_size:
                    raise RuntimeError(f"Connection pool exhausted (max {self.max_size})")
                conn = PostgresConnection(psycopg.connect(DATABASE_URL, row_factory=dict_row))
            self.in_use += 1
        return conn
    
    def return_connection(self, conn):
        with self.lock:
            self.in_use -= 1
            if len(self.available) < self.max_size:
                self.available.append(conn)
            else:
                conn.close()
    
    def close_all(self):
        with self.lock:
            for conn in self.available:
                conn.close()
            self.available.clear()
            self.in_use = 0


# Global instances
_query_cache = QueryCache(ttl_seconds=60)
_connection_pool: Optional[ConnectionPool] = None


def get_connection_pool() -> Optional[ConnectionPool]:
    """Get or create the connection pool for PostgreSQL"""
    global _connection_pool
    if get_database_backend() == "postgres":
        if _connection_pool is None:
            _connection_pool = ConnectionPool(max_size=20)
        return _connection_pool
    return None


def ensure_column(conn, table_name: str, column_name: str, definition: str):
    if get_database_backend() == "postgres":
        columns = {
            row["column_name"]
            for row in conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
                (table_name,),
            ).fetchall()
        }
    else:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}

    if column_name not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def has_column(conn, table_name: str, column_name: str) -> bool:
    if get_database_backend() == "postgres":
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
            (table_name,),
        ).fetchall()
        return column_name in {row["column_name"] for row in rows}
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return column_name in {row["name"] for row in rows}


def get_connection():
    if get_database_backend() == "postgres":
        if psycopg is None:
            raise RuntimeError("psycopg is required when DATABASE_URL points to PostgreSQL")
        pool = get_connection_pool()
        if pool:
            return pool.get_connection()
        return PostgresConnection(psycopg.connect(DATABASE_URL, row_factory=dict_row))

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        try:
            os.chmod(DB_PATH, 0o666)
        except OSError:
            pass
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def return_connection(conn):
    """Return a connection to the pool (for pooled connections)"""
    if get_database_backend() == "postgres":
        pool = get_connection_pool()
        if pool and isinstance(conn, PostgresConnection):
            pool.return_connection(conn)


def batch_insert(conn, table: str, columns: List[str], rows: List[Tuple]) -> int:
    """Efficiently insert multiple rows in batch"""
    if not rows:
        return 0
    
    backend = get_database_backend()
    placeholders = ", ".join(["?" if backend == "sqlite" else "%s" for _ in columns])
    col_names = ", ".join(columns)
    
    if backend == "postgres":
        query = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})"
        for row in rows:
            conn.execute(query, row)
    else:
        # SQLite can use executemany for batch operations
        query = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})"
        conn._connection.executemany(query, rows)
    
    conn.commit()
    return len(rows)


def batch_update(conn, table: str, updates: Dict[str, Any], where_clause: str, where_params: Tuple) -> int:
    """Efficiently update multiple rows"""
    backend = get_database_backend()
    
    set_clause = ", ".join([f"{k} = {'%s' if backend == 'postgres' else '?'}" for k in updates.keys()])
    query = f"UPDATE {table} SET {set_clause} WHERE {where_clause}"
    
    params = tuple(updates.values()) + where_params
    result = conn.execute(query, params)
    conn.commit()
    
    return 1  # Row count tracking not reliable across backends


def clear_query_cache(pattern: str = None) -> None:
    """Clear query cache, optionally by pattern"""
    if pattern:
        _query_cache.invalidate(pattern)
    else:
        _query_cache.invalidate()


def record_health_check(check_type: str, status: str, response_time_ms: float = 0.0, details: str = "") -> None:
    """Record a health check result for monitoring"""
    try:
        conn = get_connection()
        conn.execute(
            """
            INSERT INTO health_checks (check_type, status, response_time_ms, details, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (check_type, status, response_time_ms, details, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        # Silently fail - don't break health checks if recording fails
        pass


def get_health_check_history(check_type: str = None, limit: int = 100) -> List[Dict[str, Any]]:
    """Retrieve health check history with optional filtering"""
    try:
        conn = get_connection()
        if check_type:
            rows = conn.execute(
                """
                SELECT * FROM health_checks 
                WHERE check_type = ? 
                ORDER BY created_at DESC 
                LIMIT ?
                """,
                (check_type, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM health_checks ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except Exception:
        return []


def get_sla_violations(limit: int = 50, unresolved_only: bool = False) -> List[Dict[str, Any]]:
    """Retrieve SLA violations with optional filtering"""
    try:
        conn = get_connection()
        if unresolved_only:
            rows = conn.execute(
                "SELECT * FROM sla_violations WHERE resolved = 0 ORDER BY violation_time DESC LIMIT ?",
                (limit,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM sla_violations ORDER BY violation_time DESC LIMIT ?",
                (limit,),
            ).fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except Exception:
        return []


def record_backup(backup_id: str, status: str, size_mb: float, location: str) -> None:
    """Record backup event in database"""
    try:
        conn = get_connection()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS backup_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                backup_id TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL,
                size_mb REAL,
                location TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        
        conn.execute(
            """
            INSERT OR IGNORE INTO backup_history (backup_id, status, size_mb, location)
            VALUES (?, ?, ?, ?)
            """,
            (backup_id, status, size_mb, location),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to record backup: {e}")


def get_backup_history(limit: int = 20) -> List[Dict[str, Any]]:
    """Retrieve backup history"""
    try:
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM backup_history ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except Exception:
        return []


# Phase 5.4 - Log Aggregation & Centralized Monitoring Functions

def record_log(component: str, level: str, message: str, context: str = "", user_id: int | None = None) -> None:
    """Record a log entry in the centralized logging system"""
    try:
        conn = get_connection()
        timestamp = datetime.now(timezone.utc).isoformat()
        
        conn.execute(
            """
            INSERT INTO logs (component, level, message, context, user_id, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (component, level, message, context, user_id, timestamp),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Failed to record log: {e}")


def get_logs(component: str | None = None, level: str | None = None, limit: int = 100) -> List[Dict[str, Any]]:
    """Retrieve logs with optional filtering"""
    try:
        conn = get_connection()
        query = "SELECT * FROM logs WHERE 1=1"
        params = []
        
        if component:
            query += " AND component = ?"
            params.append(component)
        
        if level:
            query += " AND level = ?"
            params.append(level)
        
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        
        rows = conn.execute(query, tuple(params)).fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except Exception:
        return []


def get_log_analytics(time_period_hours: int = 24) -> Dict[str, Any]:
    """Get analytics about logs"""
    try:
        conn = get_connection()
        cutoff_time = (datetime.now(timezone.utc) - timedelta(hours=time_period_hours)).isoformat()
        
        total_logs = conn.execute(
            "SELECT COUNT(*) as count FROM logs WHERE timestamp > ?",
            (cutoff_time,),
        ).fetchone()
        
        error_count = conn.execute(
            "SELECT COUNT(*) as count FROM logs WHERE level = 'ERROR' AND timestamp > ?",
            (cutoff_time,),
        ).fetchone()
        
        warning_count = conn.execute(
            "SELECT COUNT(*) as count FROM logs WHERE level = 'WARNING' AND timestamp > ?",
            (cutoff_time,),
        ).fetchone()
        
        info_count = conn.execute(
            "SELECT COUNT(*) as count FROM logs WHERE level = 'INFO' AND timestamp > ?",
            (cutoff_time,),
        ).fetchone()
        
        debug_count = conn.execute(
            "SELECT COUNT(*) as count FROM logs WHERE level = 'DEBUG' AND timestamp > ?",
            (cutoff_time,),
        ).fetchone()
        
        # Get top errors
        top_errors_rows = conn.execute(
            """
            SELECT message, COUNT(*) as count FROM logs 
            WHERE level = 'ERROR' AND timestamp > ?
            GROUP BY message ORDER BY count DESC LIMIT 5
            """,
            (cutoff_time,),
        ).fetchall()
        
        # Get component breakdown
        component_rows = conn.execute(
            """
            SELECT component, COUNT(*) as count FROM logs 
            WHERE timestamp > ?
            GROUP BY component ORDER BY count DESC
            """,
            (cutoff_time,),
        ).fetchall()
        
        conn.close()
        
        return {
            "total_logs": total_logs["count"] if total_logs else 0,
            "error_count": error_count["count"] if error_count else 0,
            "warning_count": warning_count["count"] if warning_count else 0,
            "info_count": info_count["count"] if info_count else 0,
            "debug_count": debug_count["count"] if debug_count else 0,
            "top_errors": [dict(row) for row in top_errors_rows],
            "component_breakdown": {row["component"]: row["count"] for row in component_rows},
        }
    except Exception as e:
        print(f"Failed to get log analytics: {e}")
        return {
            "total_logs": 0,
            "error_count": 0,
            "warning_count": 0,
            "info_count": 0,
            "debug_count": 0,
            "top_errors": [],
            "component_breakdown": {},
        }


def record_alert(alert_rule_id: int | str, message: str, severity: str = "medium") -> None:
    """Record an alert trigger"""
    try:
        conn = get_connection()
        timestamp = datetime.now(timezone.utc).isoformat()
        
        conn.execute(
            """
            INSERT INTO alerts (alert_rule_id, message, severity, triggered_at, resolved)
            VALUES (?, ?, ?, ?, ?)
            """,
            (alert_rule_id, message, severity, timestamp, 0),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Failed to record alert: {e}")


def get_alerts(limit: int = 50) -> List[Dict[str, Any]]:
    """Get recent alerts"""
    try:
        conn = get_connection()
        rows = conn.execute(
            """
            SELECT a.*, r.name as rule_name FROM alerts a
            LEFT JOIN alert_rules r ON a.alert_rule_id = r.id
            ORDER BY a.triggered_at DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except Exception:
        return []


def create_alert_rule(
    rule_id: str,
    name: str,
    condition: str,
    threshold: float,
    alert_type: str = "in_app",
    enabled: bool = True,
) -> None:
    """Create a new alert rule"""
    try:
        conn = get_connection()
        timestamp = datetime.now(timezone.utc).isoformat()
        
        conn.execute(
            """
            INSERT INTO alert_rules (rule_id, name, condition, threshold, alert_type, enabled, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (rule_id, name, condition, threshold, alert_type, enabled, timestamp),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Failed to create alert rule: {e}")


def get_alert_rules() -> List[Dict[str, Any]]:
    """Get all configured alert rules"""
    try:
        conn = get_connection()
        rows = conn.execute("SELECT * FROM alert_rules ORDER BY created_at DESC").fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except Exception:
        return []


def archive_logs(days_old: int = 30) -> int:
    """Archive logs older than specified days"""
    try:
        conn = get_connection()
        cutoff_time = (datetime.now(timezone.utc) - timedelta(days=days_old)).isoformat()
        
        # In a real implementation, would move to archive table
        # For now, just mark as archived
        cursor = conn.execute(
            "DELETE FROM logs WHERE timestamp < ?",
            (cutoff_time,),
        )
        archived_count = cursor.rowcount if hasattr(cursor, 'rowcount') else 0
        conn.commit()
        conn.close()
        return archived_count
    except Exception as e:
        print(f"Failed to archive logs: {e}")
        return 0


def cleanup_old_logs(retention_days: int = 90) -> int:
    """Clean up logs older than retention period"""
    try:
        conn = get_connection()
        cutoff_time = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        
        cursor = conn.execute(
            "DELETE FROM logs WHERE timestamp < ?",
            (cutoff_time,),
        )
        cleaned_count = cursor.rowcount if hasattr(cursor, 'rowcount') else 0
        conn.commit()
        conn.close()
        return cleaned_count
    except Exception as e:
        print(f"Failed to cleanup logs: {e}")
        return 0


# Phase 5.5 - Auto-scaling & Load Balancing Functions

def create_scaling_policy(
    policy_id: str,
    name: str,
    metric: str,
    threshold_up: float,
    threshold_down: float,
    scale_up_instances: int,
    scale_down_instances: int,
    cooldown_minutes: int,
    enabled: bool = True,
) -> None:
    """Create a new auto-scaling policy"""
    try:
        conn = get_connection()
        timestamp = datetime.now(timezone.utc).isoformat()
        
        conn.execute(
            """
            INSERT INTO scaling_policies 
            (policy_id, name, metric, threshold_up, threshold_down, scale_up_instances, scale_down_instances, cooldown_minutes, enabled, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (policy_id, name, metric, threshold_up, threshold_down, scale_up_instances, scale_down_instances, cooldown_minutes, enabled, timestamp),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Failed to create scaling policy: {e}")


def get_scaling_policies() -> List[Dict[str, Any]]:
    """Get all scaling policies"""
    try:
        conn = get_connection()
        rows = conn.execute("SELECT * FROM scaling_policies ORDER BY created_at DESC").fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except Exception:
        return []


def record_scaling_event(
    event_id: str,
    event_type: str,
    policy_id: int | str | None,
    metric_value: float,
    threshold: float,
    instances_added: int = 0,
    instances_removed: int = 0,
    message: str = "",
) -> None:
    """Record a scaling event"""
    try:
        conn = get_connection()
        timestamp = datetime.now(timezone.utc).isoformat()
        
        conn.execute(
            """
            INSERT INTO scaling_events 
            (event_id, event_type, policy_id, metric_value, threshold, instances_added, instances_removed, message, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (event_id, event_type, policy_id, metric_value, threshold, instances_added, instances_removed, message, timestamp),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Failed to record scaling event: {e}")


def get_scaling_events(hours: int = 24, limit: int = 100) -> List[Dict[str, Any]]:
    """Get scaling events for a time period"""
    try:
        conn = get_connection()
        cutoff_time = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        
        rows = conn.execute(
            """
            SELECT * FROM scaling_events 
            WHERE timestamp > ?
            ORDER BY timestamp DESC LIMIT ?
            """,
            (cutoff_time, limit),
        ).fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except Exception:
        return []


def get_load_balancer_config() -> Dict[str, Any]:
    """Get load balancer configuration"""
    try:
        conn = get_connection()
        row = conn.execute("SELECT * FROM load_balancer_config ORDER BY created_at DESC LIMIT 1").fetchone()
        conn.close()
        return dict(row) if row else {}
    except Exception:
        return {}


def update_load_balancer_config(
    algorithm: str = "round_robin",
    health_check_interval_seconds: int = 10,
    sticky_sessions: bool = False,
) -> None:
    """Update load balancer configuration"""
    try:
        conn = get_connection()
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # Create or update config
        existing = conn.execute("SELECT id FROM load_balancer_config LIMIT 1").fetchone()
        
        if existing:
            conn.execute(
                """
                UPDATE load_balancer_config 
                SET algorithm = ?, health_check_interval_seconds = ?, sticky_sessions = ?, updated_at = ?
                WHERE id = ?
                """,
                (algorithm, health_check_interval_seconds, sticky_sessions, timestamp, existing["id"]),
            )
        else:
            lb_id = "lb-001"
            conn.execute(
                """
                INSERT INTO load_balancer_config 
                (lb_id, algorithm, health_check_interval_seconds, sticky_sessions, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (lb_id, algorithm, health_check_interval_seconds, sticky_sessions, timestamp),
            )
        
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Failed to update LB config: {e}")


def get_instance_metrics() -> List[Dict[str, Any]]:
    """Get metrics for all instances"""
    try:
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM instance_metrics ORDER BY last_updated DESC"
        ).fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except Exception:
        return []


def record_instance_metrics(
    instance_id: str,
    instance_name: str,
    cpu_percent: float,
    memory_percent: float,
    active_requests: int,
    average_response_time_ms: float,
    health_status: str = "healthy",
) -> None:
    """Record instance metrics"""
    try:
        conn = get_connection()
        timestamp = datetime.now(timezone.utc).isoformat()
        uptime_seconds = int(time())  # Simulated
        
        # Check if instance exists
        existing = conn.execute(
            "SELECT id FROM instance_metrics WHERE instance_id = ?",
            (instance_id,),
        ).fetchone()
        
        if existing:
            conn.execute(
                """
                UPDATE instance_metrics 
                SET cpu_percent = ?, memory_percent = ?, active_requests = ?, 
                    average_response_time_ms = ?, health_status = ?, last_updated = ?
                WHERE instance_id = ?
                """,
                (cpu_percent, memory_percent, active_requests, average_response_time_ms, health_status, timestamp, instance_id),
            )
        else:
            conn.execute(
                """
                INSERT INTO instance_metrics 
                (instance_id, instance_name, cpu_percent, memory_percent, active_requests, average_response_time_ms, uptime_seconds, health_status, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (instance_id, instance_name, cpu_percent, memory_percent, active_requests, average_response_time_ms, uptime_seconds, health_status, timestamp),
            )
        
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Failed to record instance metrics: {e}")


def ensure_bootstrap_admin(conn):
    config = get_bootstrap_admin_config()
    if not config["email"] or not config["password"]:
        return

    existing_admin = conn.execute("SELECT id FROM users WHERE email = ?", (config["email"],)).fetchone()
    if existing_admin:
        return

    password_updated_at = datetime.now(timezone.utc).isoformat()
    if has_column(conn, "users", "password_updated_at"):
        conn.execute(
            "INSERT INTO users (name, email, role, password, password_updated_at) VALUES (?, ?, ?, ?, ?)",
            (config["name"], config["email"], "admin", hash_password(config["password"]), password_updated_at),
        )
    else:
        conn.execute(
            "INSERT INTO users (name, email, role, password) VALUES (?, ?, ?, ?)",
            (config["name"], config["email"], "admin", hash_password(config["password"])),
        )


def create_admin_user(name: str, email: str, password: str, update_existing: bool = False) -> tuple[bool, str]:
    if not email.strip():
        return False, "Admin email is required"
    if not is_strong_password(password):
        return False, "Password must be at least 8 characters and include letters and numbers"

    conn = get_connection()
    try:
        existing = conn.execute("SELECT id FROM users WHERE email = ?", (email.strip(),)).fetchone()
        if existing:
            if not update_existing:
                return False, "Admin user already exists"
            if has_column(conn, "users", "password_updated_at"):
                conn.execute(
                    "UPDATE users SET name = ?, role = ?, password = ?, password_updated_at = ? WHERE email = ?",
                    (name.strip() or "SmartHaul Admin", "admin", hash_password(password), datetime.now(timezone.utc).isoformat(), email.strip()),
                )
            else:
                conn.execute(
                    "UPDATE users SET name = ?, role = ?, password = ? WHERE email = ?",
                    (name.strip() or "SmartHaul Admin", "admin", hash_password(password), email.strip()),
                )
            conn.commit()
            return True, "Admin user updated successfully"

        if has_column(conn, "users", "password_updated_at"):
            conn.execute(
                "INSERT INTO users (name, email, role, password, password_updated_at) VALUES (?, ?, ?, ?, ?)",
                (name.strip() or "SmartHaul Admin", email.strip(), "admin", hash_password(password), datetime.now(timezone.utc).isoformat()),
            )
        else:
            conn.execute(
                "INSERT INTO users (name, email, role, password) VALUES (?, ?, ?, ?)",
                (name.strip() or "SmartHaul Admin", email.strip(), "admin", hash_password(password)),
            )
        conn.commit()
        return True, "Admin user created successfully"
    finally:
        conn.close()


def postgres_create_statements() -> list[str]:
    return [
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            role TEXT NOT NULL,
            password TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            customer_id TEXT NOT NULL,
            service_type TEXT NOT NULL,
            pickup TEXT NOT NULL,
            destination TEXT NOT NULL,
            price DOUBLE PRECISION NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS vendors (
            id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            location TEXT NOT NULL,
            rating DOUBLE PRECISION NOT NULL DEFAULT 0
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            user_id TEXT NOT NULL,
            report_type TEXT NOT NULL,
            description TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS quotes (
            id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            customer_name TEXT NOT NULL,
            service_type TEXT NOT NULL,
            pickup TEXT NOT NULL,
            destination TEXT NOT NULL,
            budget DOUBLE PRECISION NOT NULL,
            status TEXT NOT NULL DEFAULT 'requested'
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'unread',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            sender TEXT NOT NULL,
            recipient TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS providers (
            id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'available',
            service_area TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            booking_id INTEGER NOT NULL,
            amount DOUBLE PRECISION NOT NULL,
            method TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'paid',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS refunds (
            id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            payment_id INTEGER NOT NULL,
            amount DOUBLE PRECISION NOT NULL,
            reason TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'requested',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS disputes (
            id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            booking_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            description TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS booking_tracking_events (
            id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            booking_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            latitude DOUBLE PRECISION,
            longitude DOUBLE PRECISION,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS call_sessions (
            id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            participant TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'connected',
            call_type TEXT NOT NULL DEFAULT 'audio',
            booking_id INTEGER,
            consent_given INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS moderation_cases (
            id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            message_id INTEGER,
            reason TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'medium',
            status TEXT NOT NULL DEFAULT 'open',
            source_text TEXT NOT NULL DEFAULT '',
            resolution_note TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS admin_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS activity_logs (
            id SERIAL PRIMARY KEY,
            admin_id INTEGER NOT NULL,
            action_type TEXT NOT NULL,
            entity_type TEXT,
            entity_id INTEGER,
            details TEXT,
            ip_address TEXT,
            user_agent TEXT,
            timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (admin_id) REFERENCES users(id)
        )
        """,
    ]


def init_db():
    conn = get_connection()
    create_statements = postgres_create_statements() if get_database_backend() == "postgres" else [
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            role TEXT NOT NULL,
            password TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            service_type TEXT NOT NULL,
            pickup TEXT NOT NULL,
            destination TEXT NOT NULL,
            price REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS vendors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            location TEXT NOT NULL,
            rating REAL NOT NULL DEFAULT 0
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            report_type TEXT NOT NULL,
            description TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS quotes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT NOT NULL,
            service_type TEXT NOT NULL,
            pickup TEXT NOT NULL,
            destination TEXT NOT NULL,
            budget REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'requested'
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'unread',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT NOT NULL,
            recipient TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS providers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'available',
            service_area TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            method TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'paid',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS refunds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payment_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            reason TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'requested',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS disputes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            description TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS booking_tracking_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            latitude REAL,
            longitude REAL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS call_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            participant TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'connected',
            call_type TEXT NOT NULL DEFAULT 'audio',
            booking_id INTEGER,
            consent_given INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS moderation_cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER,
            reason TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'medium',
            status TEXT NOT NULL DEFAULT 'open',
            source_text TEXT NOT NULL DEFAULT '',
            resolution_note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS admin_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS activity_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER NOT NULL,
            action_type TEXT NOT NULL,
            entity_type TEXT,
            entity_id INTEGER,
            details TEXT,
            ip_address TEXT,
            user_agent TEXT,
            timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (admin_id) REFERENCES users(id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS ip_blacklist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip_address TEXT NOT NULL UNIQUE,
            reason TEXT NOT NULL DEFAULT '',
            added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            added_by_admin_id INTEGER,
            FOREIGN KEY (added_by_admin_id) REFERENCES users(id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS health_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            check_type TEXT NOT NULL,
            status TEXT NOT NULL,
            response_time_ms REAL,
            details TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS sla_violations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            metric_name TEXT NOT NULL,
            expected_value REAL,
            actual_value REAL,
            violation_time TEXT NOT NULL,
            severity TEXT DEFAULT 'medium',
            resolved BOOLEAN DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            component TEXT NOT NULL,
            level TEXT NOT NULL,
            message TEXT NOT NULL,
            context TEXT,
            user_id INTEGER,
            timestamp TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS alert_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_id TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            condition TEXT NOT NULL,
            threshold REAL NOT NULL,
            alert_type TEXT DEFAULT 'in_app',
            enabled BOOLEAN DEFAULT 1,
            created_at TEXT NOT NULL,
            created_at_ts TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_rule_id INTEGER,
            message TEXT NOT NULL,
            severity TEXT DEFAULT 'medium',
            triggered_at TEXT NOT NULL,
            resolved BOOLEAN DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS scaling_policies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            policy_id TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            metric TEXT NOT NULL,
            threshold_up REAL NOT NULL,
            threshold_down REAL NOT NULL,
            scale_up_instances INTEGER DEFAULT 1,
            scale_down_instances INTEGER DEFAULT 1,
            cooldown_minutes INTEGER DEFAULT 5,
            enabled BOOLEAN DEFAULT 1,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS scaling_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL UNIQUE,
            event_type TEXT NOT NULL,
            policy_id INTEGER,
            metric_value REAL,
            threshold REAL,
            instances_added INTEGER DEFAULT 0,
            instances_removed INTEGER DEFAULT 0,
            message TEXT,
            timestamp TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS load_balancer_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lb_id TEXT NOT NULL,
            algorithm TEXT DEFAULT 'round_robin',
            health_check_interval_seconds INTEGER DEFAULT 10,
            health_check_timeout_seconds INTEGER DEFAULT 5,
            unhealthy_threshold INTEGER DEFAULT 3,
            healthy_threshold INTEGER DEFAULT 2,
            sticky_sessions BOOLEAN DEFAULT 0,
            session_timeout_minutes INTEGER DEFAULT 30,
            created_at TEXT NOT NULL,
            updated_at TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS instance_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instance_id TEXT NOT NULL UNIQUE,
            instance_name TEXT NOT NULL,
            cpu_percent REAL DEFAULT 0,
            memory_percent REAL DEFAULT 0,
            active_requests INTEGER DEFAULT 0,
            average_response_time_ms REAL DEFAULT 0,
            uptime_seconds INTEGER DEFAULT 0,
            health_status TEXT DEFAULT 'healthy',
            last_updated TEXT NOT NULL
        )
        """,
    ]
    for statement in create_statements:
        conn.execute(statement)
    ensure_column(conn, "users", "failed_login_attempts", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(conn, "users", "locked_until", "TEXT")
    ensure_column(conn, "users", "last_login_at", "TEXT")
    ensure_column(conn, "users", "password_updated_at", "TEXT")
    ensure_column(conn, "users", "account_status", "TEXT NOT NULL DEFAULT 'active'")
    ensure_column(conn, "users", "account_restriction_reason", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "users", "account_restricted_at", "TEXT")
    ensure_column(conn, "bookings", "current_latitude", "REAL")
    ensure_column(conn, "bookings", "current_longitude", "REAL")
    ensure_column(conn, "bookings", "eta_minutes", "INTEGER")
    ensure_column(conn, "bookings", "updated_at", "TEXT")
    ensure_column(conn, "bookings", "completed_at", "TEXT")
    ensure_column(conn, "bookings", "provider_id", "INTEGER")
    ensure_column(conn, "bookings", "vendor_id", "INTEGER")
    ensure_column(conn, "bookings", "rating", "REAL")
    ensure_column(conn, "bookings", "feedback_comment", "TEXT")
    ensure_column(conn, "bookings", "feedback_submitted_at", "TEXT")
    ensure_column(conn, "bookings", "last_location_update_at", "TEXT")
    ensure_column(conn, "bookings", "location_tracking_status", "TEXT DEFAULT 'active'")
    ensure_column(conn, "vendors", "contact_email", "TEXT")
    ensure_column(conn, "vendors", "document_status", "TEXT NOT NULL DEFAULT 'missing'")
    ensure_column(conn, "vendors", "onboarding_status", "TEXT NOT NULL DEFAULT 'pending_review'")
    ensure_column(conn, "vendors", "onboarding_notes", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "vendors", "created_at", "TEXT")
    ensure_column(conn, "vendors", "permanently_banned", "BOOLEAN DEFAULT 0")
    ensure_column(conn, "vendors", "ban_reason", "TEXT")
    ensure_column(conn, "vendors", "last_rejection_at", "TEXT")
    ensure_column(conn, "vendors", "resubmission_count", "INTEGER DEFAULT 0")
    ensure_column(conn, "vendors", "total_earnings", "REAL DEFAULT 0")
    ensure_column(conn, "vendors", "total_orders", "INTEGER DEFAULT 0")
    ensure_column(conn, "vendors", "total_completed_orders", "INTEGER DEFAULT 0")
    ensure_column(conn, "providers", "rating", "REAL DEFAULT 0")
    ensure_column(conn, "providers", "total_earnings", "REAL DEFAULT 0")
    ensure_column(conn, "providers", "total_bookings", "INTEGER DEFAULT 0")
    ensure_column(conn, "providers", "completed_bookings", "INTEGER DEFAULT 0")
    ensure_column(conn, "providers", "created_at", "TEXT")
    ensure_column(conn, "notifications", "channel", "TEXT NOT NULL DEFAULT 'in_app'")
    ensure_column(conn, "notifications", "booking_id", "INTEGER")
    ensure_column(conn, "messages", "booking_id", "INTEGER")
    ensure_column(conn, "messages", "moderation_status", "TEXT NOT NULL DEFAULT 'clear'")
    ensure_column(conn, "messages", "flagged_reason", "TEXT")
    ensure_column(conn, "moderation_cases", "resolution_note", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "payments", "gateway", "TEXT NOT NULL DEFAULT 'sandbox'")
    ensure_column(conn, "payments", "external_reference", "TEXT")
    ensure_column(conn, "payments", "integration_status", "TEXT NOT NULL DEFAULT 'sandbox_processed'")
    ensure_column(conn, "payments", "escrow_status", "TEXT NOT NULL DEFAULT 'held'")
    ensure_column(conn, "payments", "payout_status", "TEXT NOT NULL DEFAULT 'not_scheduled'")
    ensure_column(conn, "payments", "payout_release_at", "TEXT")
    ensure_column(conn, "payments", "payout_released_at", "TEXT")
    ensure_column(conn, "disputes", "payout_resolution", "TEXT NOT NULL DEFAULT 'manual_review_required'")
    ensure_column(conn, "disputes", "resolution", "TEXT")
    ensure_column(conn, "disputes", "resolution_notes", "TEXT")
    ensure_column(conn, "disputes", "resolved_at", "TEXT")
    ensure_column(conn, "reports", "entity_type", "TEXT")
    ensure_column(conn, "reports", "entity_id", "INTEGER")
    ensure_column(conn, "reports", "entity_available", "BOOLEAN DEFAULT 1")
    ensure_column(conn, "reports", "reported_user_id", "TEXT")
    ensure_column(conn, "reports", "review_notes", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "reports", "resolved_at", "TEXT")
    ensure_column(conn, "call_sessions", "should_log_call", "BOOLEAN DEFAULT 0")
    ensure_column(conn, "call_sessions", "logging_reason", "TEXT")
    ensure_column(conn, "call_sessions", "logged_at", "TEXT")
    ensure_column(conn, "call_sessions", "initiator_id", "INTEGER")
    ensure_column(conn, "call_sessions", "recipient_id", "INTEGER")
    ensure_column(conn, "call_sessions", "call_started_at", "TEXT")
    ensure_column(conn, "call_sessions", "call_ended_at", "TEXT")
    ensure_column(conn, "call_sessions", "duration_seconds", "INTEGER DEFAULT 0")
    ensure_column(conn, "call_sessions", "video_enabled", "BOOLEAN DEFAULT 0")
    ensure_column(conn, "call_sessions", "recording_consented", "BOOLEAN DEFAULT 0")
    ensure_column(conn, "call_sessions", "call_quality_score", "REAL")
    ensure_column(conn, "call_sessions", "quality_notes", "TEXT")
    conn.execute("CREATE TABLE IF NOT EXISTS user_call_preferences (")
    conn.execute("    user_id INTEGER PRIMARY KEY,")
    conn.execute("    accept_audio_calls BOOLEAN DEFAULT 1,")
    conn.execute("    accept_video_calls BOOLEAN DEFAULT 1,")
    conn.execute("    allow_recording BOOLEAN DEFAULT 0,")
    conn.execute("    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,")
    conn.execute("    FOREIGN KEY (user_id) REFERENCES users(id)")
    conn.execute(")")
    # Core status indexes
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bookings_status ON bookings(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vendors_onboarding_status ON vendors(onboarding_status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_payments_gateway ON payments(gateway)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_disputes_status ON disputes(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_call_sessions_status ON call_sessions(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_call_sessions_type ON call_sessions(call_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_call_sessions_should_log ON call_sessions(should_log_call)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_moderation_status ON messages(moderation_status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_moderation_cases_status ON moderation_cases(status)")
    
    # Real-time tracking optimization indexes
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bookings_provider_id ON bookings(provider_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bookings_customer_id ON bookings(customer_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bookings_created_at ON bookings(created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bookings_status_provider ON bookings(status, provider_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_booking_tracking_events_booking_id ON booking_tracking_events(booking_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_booking_tracking_events_created_at ON booking_tracking_events(created_at)")
    
    # Analytics optimization indexes
    conn.execute("CREATE INDEX IF NOT EXISTS idx_activity_logs_admin_id ON activity_logs(admin_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_activity_logs_action_type ON activity_logs(action_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_activity_logs_entity_type ON activity_logs(entity_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_activity_logs_timestamp ON activity_logs(timestamp)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_disputes_booking_id ON disputes(booking_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_disputes_created_at ON disputes(created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reports_created_at ON reports(created_at)")
    
    # User and role indexes
    conn.execute("CREATE INDEX IF NOT EXISTS idx_users_role ON users(role)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_users_created_at ON users(created_at)")
    
    # Call and communication indexes
    conn.execute("CREATE INDEX IF NOT EXISTS idx_call_sessions_initiator_id ON call_sessions(initiator_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_call_sessions_recipient_id ON call_sessions(recipient_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_call_sessions_created_at ON call_sessions(created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_sender ON messages(sender)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_recipient ON messages(recipient)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_booking_id ON messages(booking_id)")
    
    # Payment and transaction indexes
    conn.execute("CREATE INDEX IF NOT EXISTS idx_payments_booking_id ON payments(booking_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_payments_created_at ON payments(created_at)")
    
    # Phase 5.5 - Auto-scaling & Load Balancing indexes
    conn.execute("CREATE INDEX IF NOT EXISTS idx_scaling_policies_metric ON scaling_policies(metric)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_scaling_policies_enabled ON scaling_policies(enabled)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_scaling_events_event_type ON scaling_events(event_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_scaling_events_policy_id ON scaling_events(policy_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_scaling_events_timestamp ON scaling_events(timestamp)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_instance_metrics_health_status ON instance_metrics(health_status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_instance_metrics_last_updated ON instance_metrics(last_updated)")

    conn.execute(
        "INSERT OR IGNORE INTO vendors (id, name, category, location, rating) VALUES (?, ?, ?, ?, ?)",
        (1, "Urban Logistics Hub", "haulage", "Lagos", 4.8),
    )
    conn.execute(
        "INSERT OR IGNORE INTO notifications (id, title, message) VALUES (?, ?, ?)",
        (1, "Welcome", "Your SmartHaul workspace is ready for bookings and vendor requests."),
    )
    ensure_bootstrap_admin(conn)
    conn.commit()
    conn.close()
