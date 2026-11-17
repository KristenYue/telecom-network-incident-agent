"""Explicitly authorized Agent Runtime tool for a local ROS 2 workcell simulation."""

import argparse
import asyncio
from pathlib import Path
from time import monotonic
from uuid import uuid4

from agent_runtime_platform.contracts import PlannerAction
from agent_runtime_platform.tools import ToolRegistry, ToolSpec
from telecom_incident_agent.adapter import TelecomIncidentRuntimeAdapter


class InspectionPlanner:
    async def decide(self, *, request, observations, step):
        if step == 0:
            return PlannerAction(kind="tool", tool={"tool_name": "inspect_simulated_workcell"})
        result = observations[-1]
        return PlannerAction(kind="finish", result={
            "data_boundary": "ros2_simulation",
            "inspection": result.get("output"),
            "tool_status": result["status"],
        })


def inspect_ros(cancel_after):
    import rclpy
    from industrial_robot_sim.action import Inspect
    from rclpy.action import ActionClient

    rclpy.init()
    node = rclpy.create_node("agent_inspection_adapter")
    client = ActionClient(node, Inspect, "/workcell/inspect")
    progress = []
    try:
        if not client.wait_for_server(timeout_sec=2):
            return {"outcome": "server_unavailable"}
        goal = client.send_goal_async(
            Inspect.Goal(checkpoints=8),
            feedback_callback=lambda msg: progress.append(msg.feedback.inspected),
        )
        rclpy.spin_until_future_complete(node, goal, timeout_sec=2)
        if not goal.done():
            return {"outcome": "submission_unknown"}
        handle = goal.result()
        if not handle.accepted:
            return {"outcome": "rejected"}
        result = handle.get_result_async()
        cancellation_sent = False
        deadline = monotonic() + 5
        while not result.done() and monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
            if cancel_after and progress and progress[-1] >= cancel_after and not cancellation_sent:
                handle.cancel_goal_async()
                cancellation_sent = True
        if not result.done():
            return {"outcome": "result_unknown", "feedback": progress}
        value = result.result().result
        return {"outcome": value.outcome, "inspected": value.inspected, "feedback": progress}
    finally:
        client.destroy()
        node.destroy_node()
        rclpy.try_shutdown()


async def main(args):
    async def inspect():
        return await asyncio.to_thread(inspect_ros, args.cancel_after)

    adapter = TelecomIncidentRuntimeAdapter(checkpoint_path=Path(args.checkpoint))
    runtime = adapter._build_runtime(
        InspectionPlanner(), ToolRegistry([
            ToolSpec("inspect_simulated_workcell", inspect, permission="write"),
        ]),
    )
    result = await runtime.run(task_id=str(uuid4()), request="inspect local simulated workcell")
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-simulation", action="store_true")
    parser.add_argument("--cancel-after", type=int, choices=range(1, 8))
    parser.add_argument("--checkpoint", default="ros-sim-checkpoints.sqlite3")
    args = parser.parse_args()
    if not args.allow_simulation:
        parser.error("--allow-simulation is required")
    asyncio.run(main(args))
