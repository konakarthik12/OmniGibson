"""
Example script demo'ing robot manipulation control with grasping.
"""
import numpy as np

import omnigibson as og
from omnigibson.macros import gm
from omnigibson.sensors import VisionSensor
from omnigibson.utils.constants import PrimType
from omnigibson.utils.ui_utils import choose_from_options, KeyboardRobotController

GRASPING_MODES = dict(
    sticky="Sticky Mitten - Objects are magnetized when they touch the fingers and a CLOSE command is given",
    assisted="Assisted Grasping - Objects are magnetized when they touch the fingers, are within the hand, and a CLOSE command is given",
    physical="Physical Grasping - No additional grasping assistance applied",
)

# Don't use GPU dynamics and Use flatcache for performance boost
gm.USE_GPU_DYNAMICS = True
gm.ENABLE_FLATCACHE = False


def main(random_selection=False, headless=False, short_exec=False):
    """
    Robot grasping mode demo with selection
    Queries the user to select a type of grasping mode
    """
    og.log.info(f"Demo {__file__}\n    " + "*" * 80 + "\n    Description:\n" + main.__doc__ + "*" * 80)

    # Choose type of grasping
    # grasping_mode = choose_from_options(options=GRASPING_MODES, name="grasping mode", random_selection=random_selection)
    grasping_mode = "sticky"
    # Create environment configuration to use
    scene_cfg = dict(type="Scene")
    robot0_cfg = dict(
        type="Fetch",
        obs_modalities=["rgb"],  # we're just doing a grasping demo so we don't need all observation modalities
        action_type="continuous",
        action_normalize=True,
        grasping_mode=grasping_mode,
    )

    # Define objects to load
    table_cfg = dict(
        type="DatasetObject",
        name="table",
        category="breakfast_table",
        model="lcsizg",
        bounding_box=[1, 1, 0.8],
        fixed_base=True,
        position=[1.1, -0.1, 0.6],
        orientation=[0, 0, 0.707, 0.707],
    )

    chair_cfg = dict(
        type="DatasetObject",
        name="chair",
        category="straight_chair",
        model="amgwaw",
        bounding_box=None,
        fixed_base=False,
        position=[0.45, 0.65, 0.425],
        orientation=[0, 0, -0.9990215, -0.0442276],
    )
    # {
    #     "type": "DatasetObject",
    #     "name": "carpet",
    #     "category": "carpet",
    #     "model": "ctclvd",
    #     "bounding_box": [0.897, 0.568, 0.012],
    #     "prim_type": PrimType.CLOTH,
    #     "abilities": {"cloth": {}},
    #     "position": [1.35, 0, 1.3],
    # },
    box_cfg = dict(
        type="PrimitiveObject",
        name="box",
        primitive_type="Cube",
        rgba=[1.0, 0, 0, 1.0],
        size=0.05,
        position=[0.53, -0.1, 0.97],
    )

    carpet_cfg = dict(
        type="DatasetObject",
        name="carpet",
        category="carpet",
        model="ctclvd",
        prim_type=PrimType.CLOTH,
        abilities={"cloth": {}},
        size=0.05,
        position=[1.1, -0.1, 0.97],

    )

    # Compile config
    # cfg = dict(scene=scene_cfg, robots=[robot0_cfg], objects=[table_cfg, chair_cfg, box_cfg])
    cfg = dict(scene=scene_cfg, robots=[robot0_cfg], objects=[table_cfg, chair_cfg, carpet_cfg])


    # Create the environment
    env = og.Environment(configs=cfg)

    # Reset the robot
    robot = env.robots[0]
    robot.set_position([0, 0, 0])
    robot.reset()
    robot.keep_still()

    # Make the robot's camera(s) high-res
    for sensor in robot.sensors.values():
        if isinstance(sensor, VisionSensor):
            sensor.image_height = 720
            sensor.image_width = 720

    # Update the simulator's viewer camera's pose so it points towards the robot
    og.sim.viewer_camera.set_position_orientation(
        position=np.array([-2.39951, 2.26469, 2.66227]),
        orientation=np.array([-0.23898481, 0.48475231, 0.75464013, -0.37204802]),
    )

    # Create teleop controller
    action_generator = KeyboardRobotController(robot=robot)

    # Print out relevant keyboard info if using keyboard teleop
    action_generator.print_keyboard_teleop_info()

    # Other helpful user info
    print("Running demo with grasping mode {}.".format(grasping_mode))
    print("Press ESC to quit")

    # Loop control until user quits
    max_steps = -1 if not short_exec else 100
    step = 0
    while step != max_steps:
        action = action_generator.get_random_action() if random_selection else action_generator.get_teleop_action()
        for _ in range(10):
            env.step(action)
            step += 1

    # Always shut down the environment cleanly at the end
    env.close()


if __name__ == "__main__":
    main()
