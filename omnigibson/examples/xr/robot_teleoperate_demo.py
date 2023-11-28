"""
Example script for using VR controller to teleoperate a robot.
"""
import omnigibson as og
from omnigibson.utils.xr_utils import VRSys
from omnigibson.utils.ui_utils import choose_from_options

ROBOTS = {
    "FrankaPanda": "Franka Emika Panda (default)",
    "Fetch": "Mobile robot with one arm",
    "Tiago": "Mobile robot with two arms",
}


def main():
    robot_name = choose_from_options(options=ROBOTS, name="robot")
    # Create the config for generating the environment we want
    scene_cfg = dict()
    scene_cfg["type"] = "Scene"
    # Add the robot we want to load
    robot0_cfg = {
        "type": robot_name,
        "obs_modalities": ["rgb", "depth", "seg_instance", "normal", "scan", "occupancy_grid"],
        "action_normalize": False,
        "grasping_mode": "assisted",
        "controller_config": {
            "arm_0": {
                "name": "InverseKinematicsController",
                "mode": "pose_absolute_ori",
                "motor_type": "position",
            },
            "gripper_0": {
                "name": "MultiFingerGripperController", 
                "command_input_limits": (0.0, 1.0),
                "mode": "smooth", 
                "inverted": True
            }
        }
    }
    object_cfg = [
        {
            "type": "DatasetObject",
            "prim_path": "/World/breakfast_table",
            "name": "breakfast_table",
            "category": "breakfast_table",
            "model": "kwmfdg",
            "bounding_box": [2, 1, 0.4],
            "position": [0.8, 0, 0.3],
            "orientation": [0, 0, 0.707, 0.707],
        },
        {
            "type": "DatasetObject",
            "prim_path": "/World/frail",
            "name": "frail",
            "category": "frail",
            "model": "zmjovr",
            "scale": [2, 2, 2],
            "position": [0.6, -0.3, 0.5],
        },
        {
            "type": "DatasetObject",
            "prim_path": "/World/toy_figure1",
            "name": "toy_figure1",
            "category": "toy_figure",
            "model": "issvzv",
            "scale": [0.75, 0.75, 0.75],
            "position": [0.6, 0, 0.5],
        },
        {
            "type": "DatasetObject",
            "prim_path": "/World/toy_figure2",
            "name": "toy_figure2",
            "category": "toy_figure",
            "model": "nncqfn",
            "scale": [0.75, 0.75, 0.75],
            "position": [0.6, 0.1, 0.5],
        },
        {
            "type": "DatasetObject",
            "prim_path": "/World/toy_figure3",
            "name": "toy_figure3",
            "category": "toy_figure",
            "model": "eulekw",
            "scale": [0.25, 0.25, 0.25],
            "position": [0.6, 0.2, 0.5],
        },
        {
            "type": "DatasetObject",
            "prim_path": "/World/toy_figure4",
            "name": "toy_figure4",
            "category": "toy_figure",
            "model": "yxiksm",
            "scale": [0.25, 0.25, 0.25],
            "position": [0.6, 0.3, 0.5],
        },
        {
            "type": "DatasetObject",
            "prim_path": "/World/toy_figure5",
            "name": "toy_figure5",
            "category": "toy_figure",
            "model": "wvpqbf",
            "scale": [0.75, 0.75, 0.75],
            "position": [0.6, 0.4, 0.5],
        },
    ]
    cfg = dict(scene=scene_cfg, robots=[robot0_cfg], objects=object_cfg)

    # Create the environment
    env = og.Environment(configs=cfg, action_timestep=1/60., physics_timestep=1/240.)
    env.reset()
    # update viewer camera pose
    og.sim.viewer_camera.set_position_orientation([-0.22, 0.99, 1.09], [-0.14, 0.47, 0.84, -0.23])

    # Start vrsys 
    vr_robot = env.robots[0]
    vrsys = VRSys(system="SteamVR", vr_robot=vr_robot, show_controller=True, disable_display_output=True, align_anchor_to_robot_base=True)
    vrsys.start()
    # tracker variable of whether the robot is attached to the VR system
    prev_robot_attached = False
    # main simulation loop
    for _ in range(10000):
        if og.sim.is_playing():
            vr_data = vrsys.step()
            if vr_data["robot_attached"] == True and prev_robot_attached == False:
                # The user just pressed the grip, so snap the VR right controller to the robot's right arm
                if vr_robot.model_name == "Tiago":
                    # Tiago's default arm is the left arm
                    robot_eef_position = vr_robot.links[vr_robot.eef_link_names["right"]].get_position()
                else:
                    robot_eef_position = vr_robot.links[vr_robot.eef_link_names[vr_robot.default_arm]].get_position()
                base_rotation = vr_robot.get_orientation()
                vrsys.snap_device_to_robot_eef(robot_eef_position=robot_eef_position, base_rotation=base_rotation)
            else:
                action = vr_robot.gen_action_from_vr_data(vr_data)
                env.step(action)   
            prev_robot_attached = vr_data["robot_attached"]
    # Shut down the environment cleanly at the end
    vrsys.stop()
    env.close()

if __name__ == "__main__":
    main()