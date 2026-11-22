"""Synthetic vehicle services: no physical vehicle or safety-critical controls."""
import json
import sqlite3
import time
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from agent_runtime_platform.contracts import PlannerAction
from agent_runtime_platform.tools import ToolRegistry, ToolSpec


class CabinTemperature(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    celsius: float = Field(ge=16, le=30)


VEHICLE_KNOWLEDGE = {
    "tire_pressure": "项目阈值只用于演示；核对车型规定的冷态胎压。存在告警时由授权人员检查，不自动执行车辆控制。",
    "battery": "电量是仿真遥测百分比，不等同于电池健康度；过期数据不能作为当前状态。",
    "door": "车门信号只读，不推导车锁或人员状态。",
    "climate": "仿真空调温度范围16至30摄氏度，写操作需要显式确认。",
    "freshness": "按采样时间判断数据新鲜度，补传接收时间不能把旧数据变成新状态。",
}


class VehicleService:
    """Single-process demo; bounded offline buffer and durable command ledger."""
    def __init__(self, path, *, capacity=32):
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.capacity = capacity
        with self.connect() as db:
            db.executescript("""CREATE TABLE IF NOT EXISTS telemetry(
              seq INTEGER PRIMARY KEY, event_time REAL, received_at REAL, payload TEXT, delivered INTEGER);
              CREATE TABLE IF NOT EXISTS commands(key TEXT PRIMARY KEY, temperature REAL);
              CREATE TABLE IF NOT EXISTS cabin(id INTEGER PRIMARY KEY, temperature REAL);
              INSERT OR IGNORE INTO cabin VALUES(1,24);""")

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def ingest(self, sequence, payload, *, event_time=None, online=True):
        if not isinstance(sequence, int) or sequence < 0:
            raise ValueError("invalid sequence")
        now = time.time()
        event_time = now if event_time is None else event_time
        if event_time > now + 1:
            raise ValueError("future telemetry")
        encoded = json.dumps(payload, sort_keys=True)
        with self.connect() as db:
            old = db.execute("SELECT payload,event_time FROM telemetry WHERE seq=?", (sequence,)).fetchone()
            if old:
                if old[0] != encoded:
                    raise ValueError("sequence payload conflict")
                return {"outcome": "duplicate", "sequence": sequence}
            if not online and db.execute("SELECT COUNT(*) FROM telemetry WHERE delivered=0").fetchone()[0] >= self.capacity:
                raise OverflowError("offline buffer full; sample rejected")
            db.execute("INSERT INTO telemetry VALUES(?,?,?,?,?)", (sequence,event_time,now,encoded,int(online)))
        return {"outcome": "delivered" if online else "buffered", "sequence": sequence}

    def reconnect(self):
        with self.connect() as db:
            count = db.execute("SELECT COUNT(*) FROM telemetry WHERE delivered=0").fetchone()[0]
            db.execute("UPDATE telemetry SET delivered=1,received_at=? WHERE delivered=0", (time.time(),))
        return {"flushed": count, "transport": "local_cloud_delivery_simulation"}

    def latest(self, max_age_seconds=30):
        with self.connect() as db:
            row = db.execute("SELECT seq,event_time,received_at,payload FROM telemetry WHERE delivered=1 ORDER BY event_time DESC,seq DESC LIMIT 1").fetchone()
        if not row:
            return {"available": False, "data_boundary": "vehicle_simulation"}
        age = max(0, time.time()-row[1])
        return {"available": True, "sequence": row[0], "event_time": row[1], "received_at": row[2],
                "age_seconds": age, "stale": age > max_age_seconds, "signals": json.loads(row[3]),
                "data_boundary": "vehicle_simulation"}

    def tire_pressure(self):
        snapshot = self.latest()
        if not snapshot["available"] or snapshot["stale"]:
            return {"outcome": "unknown", "reason": "missing_or_stale_telemetry", "snapshot": snapshot}
        pressures = snapshot["signals"].get("tire_kpa", {})
        return {"outcome": "observed", "low_tires": [name for name,value in pressures.items() if value < 220],
                "threshold_kpa": 220, "threshold_source": "project_demo_not_vehicle_spec", "snapshot": snapshot}

    def set_temperature(self, celsius, *, runtime_context):
        temperature = CabinTemperature(celsius=celsius).celsius
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            key = runtime_context.idempotency_key
            old = db.execute("SELECT temperature FROM commands WHERE key=?", (key,)).fetchone()
            if old and old[0] != temperature:
                raise ValueError("command idempotency conflict")
            if not old:
                db.execute("INSERT INTO commands VALUES(?,?)", (key,temperature))
                db.execute("UPDATE cabin SET temperature=? WHERE id=1", (temperature,))
        return {"outcome": "applied", "celsius": temperature, "replayed": bool(old), "data_boundary": "vehicle_simulation"}

    def registry(self):
        def knowledge(topic):
            if topic not in VEHICLE_KNOWLEDGE:
                raise ValueError("unknown vehicle knowledge topic")
            return {"document_id": "vehicle-"+topic, "revision": "1",
                    "text": VEHICLE_KNOWLEDGE[topic], "source": "project_authored_simulation_notes"}
        return ToolRegistry([
            ToolSpec("get_vehicle_status", self.latest),
            ToolSpec("get_tire_pressure", self.tire_pressure),
            ToolSpec("search_vehicle_knowledge", knowledge),
            ToolSpec("set_cabin_temperature", self.set_temperature, permission="dangerous", replay_safe=True, inject_context=True),
        ])


class VehiclePlanner:
    """Deterministic comparator. Live model planner is a separate acceptance item."""
    def __init__(self, *, temperature=None):
        self.temperature = temperature

    async def decide(self, *, request, observations, step):
        tools = [o for o in observations if o.get("kind") == "tool_result"]
        if not tools:
            call = {"tool_name": "get_tire_pressure", "arguments": {}} if self.temperature is None else {
                "tool_name": "set_cabin_temperature", "arguments": {"celsius": CabinTemperature(celsius=self.temperature).celsius}}
            return PlannerAction(kind="tool", tool=call)
        if self.temperature is None and not any(t["tool_name"] == "search_vehicle_knowledge" for t in tools):
            return PlannerAction(kind="tool", tool={"tool_name": "search_vehicle_knowledge", "arguments": {"topic": "tire_pressure"}})
        observed = tools[-1]
        return PlannerAction(kind="finish", result={"planner_mode": "rule_baseline", "evidence": tools,
            "explanation": "Use recorded signal and project threshold; verify vehicle-specific specification before action.",
            "data_boundary": "vehicle_simulation"})
