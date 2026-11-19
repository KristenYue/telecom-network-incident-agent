"""ROS2 Service/Action transport. Imports ROS only when explicitly selected."""
from time import monotonic


class RosWorkcellTransport:
    boundary = "ros2_logic_simulation"

    def status(self):
        import rclpy
        from std_srvs.srv import Trigger
        context = rclpy.Context()
        rclpy.init(context=context)
        node = rclpy.create_node("agent_status_client", context=context)
        client = node.create_client(Trigger, "/workcell/get_status")
        try:
            if not client.wait_for_service(timeout_sec=15):
                return {"state": "OFFLINE", "data_boundary": self.boundary}
            future = client.call_async(Trigger.Request())
            rclpy.spin_until_future_complete(node, future, timeout_sec=2)
            response = future.result() if future.done() else None
            return {"state": response.message if response and response.success else "UNKNOWN",
                    "data_boundary": self.boundary}
        finally:
            node.destroy_node()
            rclpy.shutdown(context=context)

    def inspect(self, checkpoints, feedback, canceled):
        import rclpy
        from action_msgs.msg import GoalStatus
        from industrial_robot_sim.action import Inspect
        from rclpy.action import ActionClient
        context = rclpy.Context()
        rclpy.init(context=context)
        node = rclpy.create_node("agent_skill_client", context=context)
        client = ActionClient(node, Inspect, "/workcell/inspect")
        try:
            if canceled():
                return {"outcome": "canceled", "inspected": 0}
            if not client.wait_for_server(timeout_sec=15):
                return {"outcome": "unavailable", "retry_safe": True, "inspected": 0}
            goal = client.send_goal_async(Inspect.Goal(checkpoints=checkpoints),
                feedback_callback=lambda msg: feedback({"inspected": msg.feedback.inspected, "total": checkpoints}))
            rclpy.spin_until_future_complete(node, goal, timeout_sec=5)
            if not goal.done():
                return {"outcome": "result_unknown", "retry_safe": False}
            handle = goal.result()
            if not handle.accepted:
                return {"outcome": "rejected", "retry_safe": True, "inspected": 0}
            result = handle.get_result_async()
            deadline = monotonic() + 12
            cancel_sent = False
            while not result.done() and monotonic() < deadline:
                rclpy.spin_once(node, timeout_sec=.05)
                if canceled() and not cancel_sent:
                    handle.cancel_goal_async()
                    cancel_sent = True
            if not result.done():
                handle.cancel_goal_async()
                return {"outcome": "result_unknown", "retry_safe": False, "cancel_requested": True}
            envelope = result.result()
            outcome = {GoalStatus.STATUS_SUCCEEDED: "completed", GoalStatus.STATUS_CANCELED: "canceled"}.get(envelope.status, "failed")
            return {"outcome": outcome, "inspected": envelope.result.inspected,
                    "ros_status": envelope.status, "cancel_requested": cancel_sent}
        finally:
            client.destroy()
            node.destroy_node()
            rclpy.shutdown(context=context)
