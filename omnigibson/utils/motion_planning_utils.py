import numpy as np
from math import ceil

import omnigibson as og
from omnigibson.macros import create_module_macros
from omnigibson.object_states import ContactBodies
import omnigibson.utils.transform_utils as T
from omnigibson.utils.control_utils import IKSolver
from pxr import PhysicsSchemaTools, Gf

m = create_module_macros(module_path=__file__)
m.ANGLE_DIFF = 0.3
m.DIST_DIFF = 0.1

def _wrap_angle(theta):
    """"
    Converts an angle to the range [-pi, pi).

    Args:
        theta (float): angle in radians

    Returns:
        float: angle in radians in range [-pi, pi)
    """
    return (theta + np.pi) % (2 * np.pi) - np.pi


def plan_base_motion(
    robot,
    end_conf,
    context,
    planning_time=15.0,
):
    """
    Plans a base motion to a 2d pose

    Args:
        robot (omnigibson.object_states.Robot): Robot object to plan for
        end_conf (Iterable): [x, y, yaw] 2d pose to plan to
        context (PlanningContext): Context to plan in that includes the robot copy
        planning_time (float): Time to plan for
    
    Returns:
        Array of arrays: Array of 2d poses that the robot should navigate to
    """
    from ompl import base as ob
    from ompl import geometric as ompl_geo

    class CustomMotionValidator(ob.MotionValidator):

        def __init__(self, si, space):
            super(CustomMotionValidator, self).__init__(si)
            self.si = si
            self.space = space

        def checkMotion(self, s1, s2):
            if not self.si.isValid(s2):
                return False

            start = np.array([s1.getX(), s1.getY(), s1.getYaw()])
            goal = np.array([s2.getX(), s2.getY(), s2.getYaw()])
            segment_theta = self.get_angle_between_poses(start, goal)

            # Start rotation                
            if not self.is_valid_rotation(self.si, start, segment_theta):
                return False

            # Navigation
            dist = np.linalg.norm(goal[:2] - start[:2])
            num_points = ceil(dist / m.DIST_DIFF) + 1
            nav_x = np.linspace(start[0], goal[0], num_points).tolist()
            nav_y = np.linspace(start[1], goal[1], num_points).tolist()
            for i in range(num_points):
                state = create_state(self.si, nav_x[i], nav_y[i], segment_theta)
                if not self.si.isValid(state()):
                    return False
                
            # Goal rotation
            if not self.is_valid_rotation(self.si, [goal[0], goal[1], segment_theta], goal[2]):
                return False

            return True
        
        @staticmethod
        def is_valid_rotation(si, start_conf, final_orientation):
            diff = _wrap_angle(final_orientation - start_conf[2])
            direction = np.sign(diff)
            diff = abs(diff)
            num_points = ceil(diff / m.ANGLE_DIFF) + 1
            nav_angle = np.linspace(0.0, diff, num_points) * direction
            angles = nav_angle + start_conf[2]
            for i in range(num_points):
                state = create_state(si.getStateSpace(), start_conf[0], start_conf[1], angles[i])
                if not si.isValid(state()):
                    return False
            return True
        
        @staticmethod
        # Get angle between 2d robot poses
        def get_angle_between_poses(p1, p2):
            segment = []
            segment.append(p2[0] - p1[0])
            segment.append(p2[1] - p1[1])
            return np.arctan2(segment[1], segment[0])
    
    def create_state(space, x, y, yaw):
        state = ob.State(space)
        state().setX(x)
        state().setY(y)
        state().setYaw(_wrap_angle(yaw))
        return state
    
    def state_valid_fn(q):
        x = q.getX()
        y = q.getY()
        yaw = q.getYaw()
        pose = ([x, y, 0.0], T.euler2quat((0, 0, yaw)))
        return not set_base_and_detect_collision(context, pose)
    
    def remove_unnecessary_rotations(path):
        """
        Removes unnecessary rotations from a path when possible for the base where the yaw for each pose in the path is in the direction of the
        the position of the next pose in the path

        Args:
            path (Array of arrays): Array of 2d poses
        
        Returns:
            Array of numpy arrays: Array of 2d poses with unnecessary rotations removed
        """
        # Start at the same starting pose
        new_path = [path[0]]

        # Process every intermediate waypoint
        for i in range(1, len(path) - 1):
            # compute the yaw you'd be at when arriving into path[i] and departing from it
            arriving_yaw = CustomMotionValidator.get_angle_between_poses(path[i-1], path[i])
            departing_yaw = CustomMotionValidator.get_angle_between_poses(path[i], path[i+1])

            # check if you are able to make that rotation directly. 
            arriving_state = (path[i][0], path[i][1], arriving_yaw)
            if CustomMotionValidator.is_valid_rotation(si, arriving_state, departing_yaw):
                # Then use the arriving yaw directly
                new_path.append(arriving_state)
            else:
                # Otherwise, keep the waypoint
                new_path.append(path[i])

        # Don't forget to add back the same ending pose
        new_path.append(path[-1])

        return new_path

    pos = robot.get_position()
    yaw = T.quat2euler(robot.get_orientation())[2]
    start_conf = (pos[0], pos[1], yaw)

    # create an SE(2) state space
    space = ob.SE2StateSpace()

    # set lower and upper bounds
    bbox_vals = []
    for floor in filter(lambda o: o.category == "floors", og.sim.scene.objects):
        bbox_vals += floor.aabb[0][:2].tolist()
        bbox_vals += floor.aabb[1][:2].tolist()
    bounds = ob.RealVectorBounds(2)
    bounds.setLow(min(bbox_vals))
    bounds.setHigh(max(bbox_vals))
    space.setBounds(bounds)

    # create a simple setup object
    ss = ompl_geo.SimpleSetup(space)
    ss.setStateValidityChecker(ob.StateValidityCheckerFn(state_valid_fn))

    si = ss.getSpaceInformation()
    si.setMotionValidator(CustomMotionValidator(si, space))
    # TODO: Try changing to RRTConnect in the future. Currently using RRT because movement is not direction invariant. Can change to RRTConnect
    # possibly if hasSymmetricInterpolate is set to False for the state space. Doc here https://ompl.kavrakilab.org/classompl_1_1base_1_1StateSpace.html
    planner = ompl_geo.RRT(si)
    ss.setPlanner(planner)

    start = create_state(space, start_conf[0], start_conf[1], start_conf[2])
    print(start)

    goal = create_state(space, end_conf[0], end_conf[1], end_conf[2])
    print(goal)

    ss.setStartAndGoalStates(start, goal)
    if not state_valid_fn(start()) or not state_valid_fn(goal()):
        return
      
    solved = ss.solve(planning_time)

    if solved:
        # try to shorten the path
        ss.simplifySolution()
        sol_path = ss.getSolutionPath()
        return_path = []
        for i in range(sol_path.getStateCount()):
            x = sol_path.getState(i).getX()
            y = sol_path.getState(i).getY()
            yaw = sol_path.getState(i).getYaw()
            return_path.append([x, y, yaw])
        return remove_unnecessary_rotations(return_path)
    return None

def plan_arm_motion(   
    robot,
    end_conf,
    context,
    planning_time=15.0,
    torso_fixed=True,
):
    """
    Plans an arm motion to a final joint position

    Args:
        robot (BaseRobot): Robot object to plan for
        end_conf (Iterable): Final joint position to plan to
        context (PlanningContext): Context to plan in that includes the robot copy
        planning_time (float): Time to plan for
    
    Returns:
        Array of arrays: Array of joint positions that the robot should navigate to
    """
    from ompl import base as ob
    from ompl import geometric as ompl_geo

    if torso_fixed:
        joint_control_idx = robot.arm_control_idx[robot.default_arm]
        dim = len(joint_control_idx)
        initial_joint_pos = np.array(robot.get_joint_positions()[joint_control_idx])
        control_idx_in_joint_pos = np.arange(dim)
    else:
        joint_control_idx = np.concatenate([robot.trunk_control_idx, robot.arm_control_idx[robot.default_arm]])
        dim = len(joint_control_idx)
        if "combined" in robot.robot_arm_descriptor_yamls:
            joint_combined_idx = np.concatenate([robot.trunk_control_idx, robot.arm_control_idx["combined"]])
            initial_joint_pos = np.array(robot.get_joint_positions()[joint_combined_idx])
            control_idx_in_joint_pos = np.where(np.in1d(joint_combined_idx, joint_control_idx))[0]
        else:
            initial_joint_pos = np.array(robot.get_joint_positions()[joint_control_idx])
            control_idx_in_joint_pos = np.arange(dim)

    def state_valid_fn(q):
        joint_pos = initial_joint_pos
        joint_pos[control_idx_in_joint_pos] = [q[i] for i in range(dim)]
        return not set_arm_and_detect_collision(context, joint_pos)
    
    # create an SE2 state space
    space = ob.RealVectorStateSpace(dim)

    # set lower and upper bounds
    bounds = ob.RealVectorBounds(dim)
    joints = np.array([joint for joint in robot.joints.values()])
    arm_joints = joints[joint_control_idx]
    for i, joint in enumerate(arm_joints):
        if end_conf[i] > joint.upper_limit:
            end_conf[i] = joint.upper_limit
        if end_conf[i] < joint.lower_limit:
            end_conf[i] = joint.lower_limit
        if joint.upper_limit - joint.lower_limit > 2 * np.pi:
            bounds.setLow(i, 0.0)
            bounds.setHigh(i, 2 * np.pi)
        else:
            bounds.setLow(i, float(joint.lower_limit))
            bounds.setHigh(i, float(joint.upper_limit))
    space.setBounds(bounds)

    # create a simple setup object
    ss = ompl_geo.SimpleSetup(space)
    ss.setStateValidityChecker(ob.StateValidityCheckerFn(state_valid_fn))

    si = ss.getSpaceInformation()
    planner = ompl_geo.BITstar(si)
    ss.setPlanner(planner)

    start_conf = robot.get_joint_positions()[joint_control_idx]
    start = ob.State(space)
    for i in range(dim):
        start[i] = float(start_conf[i])

    goal = ob.State(space)
    for i in range(dim):
        goal[i] = float(end_conf[i])
    ss.setStartAndGoalStates(start, goal)

    if not state_valid_fn(start) or not state_valid_fn(goal):
        return

    # this will automatically choose a default planner with
    # default parameters
    solved = ss.solve(planning_time)

    if solved:
        # try to shorten the path
        # ss.simplifySolution()

        sol_path = ss.getSolutionPath()
        return_path = []
        for i in range(sol_path.getStateCount()):
            joint_pos = [sol_path.getState(i)[j] for j in range(dim)]
            return_path.append(joint_pos)
        return return_path
    return None

def plan_arm_motion_ik(   
    robot,
    end_conf,
    context,
    planning_time=15.0,
    torso_fixed=True,
):
    """
    Plans an arm motion to a final end effector pose

    Args:
        robot (BaseRobot): Robot object to plan for
        end_conf (Iterable): Final end effector pose to plan to
        context (PlanningContext): Context to plan in that includes the robot copy
        planning_time (float): Time to plan for
    
    Returns:
        Array of arrays: Array of end effector pose that the robot should navigate to
    """
    from ompl import base as ob
    from ompl import geometric as ompl_geo

    DOF = 6

    if torso_fixed:
        joint_control_idx = robot.arm_control_idx[robot.default_arm]
        dim = len(joint_control_idx)
        initial_joint_pos = np.array(robot.get_joint_positions()[joint_control_idx])
        control_idx_in_joint_pos = np.arange(dim)
        robot_description_path = robot.robot_arm_descriptor_yamls["left_fixed"]
    else:
        joint_control_idx = np.concatenate([robot.trunk_control_idx, robot.arm_control_idx[robot.default_arm]])
        dim = len(joint_control_idx)
        if "combined" in robot.robot_arm_descriptor_yamls:
            joint_combined_idx = np.concatenate([robot.trunk_control_idx, robot.arm_control_idx["combined"]])
            initial_joint_pos = np.array(robot.get_joint_positions()[joint_combined_idx])
            control_idx_in_joint_pos = np.where(np.in1d(joint_combined_idx, joint_control_idx))[0]
        else:
            initial_joint_pos = np.array(robot.get_joint_positions()[joint_control_idx])
            control_idx_in_joint_pos = np.arange(dim)  
        robot_description_path = robot.robot_arm_descriptor_yamls[robot.default_arm]

    ik_solver = IKSolver(
        robot_description_path=robot_description_path,
        robot_urdf_path=robot.urdf_path,
        default_joint_pos=robot.default_joint_pos[joint_control_idx],
        eef_name=robot.eef_link_names[robot.default_arm],
    )

    def state_valid_fn(q):
        joint_pos = initial_joint_pos
        eef_pose = [q[i] for i in range(6)]
        control_joint_pos = ik_solver.solve(
            target_pos=eef_pose[:3],
            target_quat=T.axisangle2quat(eef_pose[3:]),
            max_iterations=1000,
        )

        if control_joint_pos is None:
            return False
        joint_pos[control_idx_in_joint_pos] = control_joint_pos
        return not set_arm_and_detect_collision(context, joint_pos)
    
    # create an SE2 state space
    space = ob.RealVectorStateSpace(DOF)

    # set lower and upper bounds for eef position
    bounds = ob.RealVectorBounds(DOF)

    EEF_X_LIM = [-0.8, 0.8]
    EEF_Y_LIM = [-0.8, 0.8]
    EEF_Z_LIM = [-2.0, 2.0]
    bounds.setLow(0, EEF_X_LIM[0])
    bounds.setHigh(0, EEF_X_LIM[1])
    bounds.setLow(1, EEF_Y_LIM[0])
    bounds.setHigh(1, EEF_Y_LIM[1])
    bounds.setLow(2, EEF_Z_LIM[0])
    bounds.setHigh(2, EEF_Z_LIM[1])
    
    # # set lower and upper bounds for eef orientation (axis angle bounds)
    for i in range(3, 6):
        bounds.setLow(i, -np.pi)
        bounds.setHigh(i, np.pi)
    space.setBounds(bounds)

    # create a simple setup object
    ss = ompl_geo.SimpleSetup(space)
    ss.setStateValidityChecker(ob.StateValidityCheckerFn(state_valid_fn))

    si = ss.getSpaceInformation()
    planner = ompl_geo.BITstar(si)
    ss.setPlanner(planner)

    start_conf = np.append(robot.get_relative_eef_position(), T.quat2axisangle(robot.get_relative_eef_orientation()))
    # do fk
    start = ob.State(space)
    for i in range(DOF):
        start[i] = float(start_conf[i])

    goal = ob.State(space)
    for i in range(DOF):
        goal[i] = float(end_conf[i])
    ss.setStartAndGoalStates(start, goal)

    if not state_valid_fn(start) or not state_valid_fn(goal):
        return

    # this will automatically choose a default planner with
    # default parameters
    solved = ss.solve(planning_time)

    if solved:
        # try to shorten the path
        # ss.simplifySolution()

        sol_path = ss.getSolutionPath()
        return_path = []
        for i in range(sol_path.getStateCount()):
            eef_pose = [sol_path.getState(i)[j] for j in range(DOF)]
            return_path.append(eef_pose)
        return return_path
    return None

def set_base_and_detect_collision(context, pose):
    """
    Moves the robot and detects robot collisions with the environment and itself

    Args:
        context (PlanningContext): Context to plan in that includes the robot copy
        pose (Array): Pose in the world frame to check for collisions at
    
    Returns:
        bool: Whether the robot is in collision
    """
    robot_copy = context.robot_copy
    robot_copy_type = context.robot_copy_type

    translation = Gf.Vec3d(*np.array(pose[0], dtype=float))
    robot_copy.prims[robot_copy_type].GetAttribute("xformOp:translate").Set(translation)

    orientation = np.array(pose[1], dtype=float)[[3, 0, 1, 2]]
    robot_copy.prims[robot_copy_type].GetAttribute("xformOp:orient").Set(Gf.Quatd(*orientation)) 

    return detect_robot_collision(context)

def set_arm_and_detect_collision(context, joint_pos):
    """
    Sets joint positions of the robot and detects robot collisions with the environment and itself

    Args:
        context (PlanningContext): Context to plan in that includes the robot copy
        joint_pos (Array): Joint positions to set the robot to
    
    Returns:
        bool: Whether the robot is in a valid state i.e. not in collision
    """
    robot_copy = context.robot_copy
    robot_copy_type = context.robot_copy_type
    
    arm_links = context.robot.manipulation_link_names
    link_poses = context.fk_solver.get_link_poses(joint_pos, arm_links)

    for link in arm_links:
        pose = link_poses[link]
        if link in robot_copy.meshes[robot_copy_type].keys():
            for mesh_name, mesh in robot_copy.meshes[robot_copy_type][link].items():
                relative_pose = robot_copy.relative_poses[robot_copy_type][link][mesh_name]
                mesh_pose = T.pose_transform(*pose, *relative_pose)
                translation = Gf.Vec3d(*np.array(mesh_pose[0], dtype=float))
                mesh.GetAttribute("xformOp:translate").Set(translation)
                orientation = np.array(mesh_pose[1], dtype=float)[[3, 0, 1, 2]]
                mesh.GetAttribute("xformOp:orient").Set(Gf.Quatd(*orientation))


    return detect_robot_collision(context)

def detect_robot_collision(context):
    """
    Detects robot collisions

    Args:
        context (PlanningContext): Context to plan in that includes the robot copy
    
    Returns:
        bool: Whether the robot is in collision
    """
    robot_copy = context.robot_copy
    robot_copy_type = context.robot_copy_type

    # Define function for checking overlap
    valid_hit = False
    mesh_path = None

    def overlap_callback(hit):
        nonlocal valid_hit
        
        valid_hit = hit.rigid_body not in context.disabled_collision_pairs_dict[mesh_path]

        return not valid_hit

    for meshes in robot_copy.meshes[robot_copy_type].values():
        for mesh in meshes.values():
            if valid_hit:
                return valid_hit
            mesh_path = mesh.GetPrimPath().pathString
            mesh_id = PhysicsSchemaTools.encodeSdfPath(mesh_path)
            if mesh.GetTypeName() == "Mesh":
                og.sim.psqi.overlap_mesh(*mesh_id, reportFn=overlap_callback)
            else:
                og.sim.psqi.overlap_shape(*mesh_id, reportFn=overlap_callback)
        
    return valid_hit

def detect_robot_collision_in_sim(robot, filter_objs=[], ignore_obj_in_hand=True):
    """
    Detects robot collisions with the environment, but not with itself using the ContactBodies API

    Args:
        robot (BaseRobot): Robot object to detect collisions for
        filter_objs (Array of StatefulObject): Objects to ignore collisions with
        ignore_obj_in_hand (bool): Whether to ignore collisions with the object in the robot's hand
    
    Returns:
        bool: Whether the robot is in collision
    """
    filter_categories = ["floors"]
    
    obj_in_hand = robot._ag_obj_in_hand[robot.default_arm]
    if obj_in_hand is not None and ignore_obj_in_hand:
        filter_objs.append(obj_in_hand)

    collision_prims = list(robot.states[ContactBodies].get_value(ignore_objs=tuple(filter_objs)))

    for col_prim in collision_prims:
        tokens = col_prim.prim_path.split("/")
        obj_prim_path = "/".join(tokens[:-1])
        col_obj = og.sim.scene.object_registry("prim_path", obj_prim_path)
        if col_obj.category in filter_categories:
            collision_prims.remove(col_prim)
    return len(collision_prims) > 0
