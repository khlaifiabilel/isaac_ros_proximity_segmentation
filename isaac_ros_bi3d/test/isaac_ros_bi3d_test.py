# Copyright (c) 2022, NVIDIA CORPORATION.  All rights reserved.
#
# NVIDIA CORPORATION and its licensors retain all intellectual property
# and proprietary rights in and to this software, related documentation
# and any modifications thereto.  Any use, reproduction, disclosure or
# distribution of this software and related documentation without an express
# license agreement from NVIDIA CORPORATION is strictly prohibited.

import os
import subprocess
import time

from isaac_ros_bi3d_interfaces.msg import Bi3DInferenceParametersArray
from isaac_ros_test import IsaacROSBaseTest

from launch_ros.actions import ComposableNodeContainer
from launch_ros.descriptions import ComposableNode

import pytest
import rclpy

from sensor_msgs.msg import Image
from stereo_msgs.msg import DisparityImage


@pytest.mark.rostest
def generate_test_description():
    dir_path = os.path.dirname(os.path.realpath(__file__))
    featnet_engine_file_path = '/tmp/dummy_bi3dnet_featnet.engine'
    segnet_engine_file_path = '/tmp/dummy_bi3dnet_segnet.engine'

    if not os.path.isfile(featnet_engine_file_path):
        args = [
            '/usr/src/tensorrt/bin/trtexec',
            f'--saveEngine={featnet_engine_file_path}',
            f'--onnx={dir_path}/dummy_featnet_model.onnx'
        ]
        print('Generating model engine file by command: ', ' '.join(args))
        result = subprocess.run(
            args,
            env=os.environ,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        if result.returncode != 0:
            raise Exception(
                f'Failed to convert with status: {result.returncode}.\n'
                f'stderr:\n' + result.stderr.decode('utf-8')
            )
    if not os.path.isfile(segnet_engine_file_path):
        args = [
            '/usr/src/tensorrt/bin/trtexec',
            f'--saveEngine={segnet_engine_file_path}',
            f'--onnx={dir_path}/dummy_segnet_model.onnx'
        ]
        print('Generating model engine file by command: ', ' '.join(args))
        result = subprocess.run(
            args,
            env=os.environ,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        if result.returncode != 0:
            raise Exception(
                f'Failed to convert with status: {result.returncode}.\n'
                f'stderr:\n' + result.stderr.decode('utf-8')
            )

    bi3d_node = ComposableNode(
        name='bi3d',
        package='isaac_ros_bi3d',
        plugin='nvidia::isaac_ros::bi3d::Bi3DNode',
        namespace=IsaacROSBi3DTest.generate_namespace(),
        parameters=[{'featnet_engine_file_path': featnet_engine_file_path,
                     'segnet_engine_file_path': segnet_engine_file_path,
                     'featnet_output_layers_name': ['97'],
                     'segnet_output_layers_name': ['294'],
                     'max_disparity_values': 1}]
    )

    container = ComposableNodeContainer(
        name='bi3d_container',
        namespace='',
        package='rclcpp_components',
        executable='component_container',
        composable_node_descriptions=[bi3d_node],
        output='screen',
        arguments=['--ros-args', '--log-level', 'info']
    )
    return IsaacROSBi3DTest.generate_test_description([container])


class IsaacROSBi3DTest(IsaacROSBaseTest):
    IMAGE_HEIGHT = 576
    IMAGE_WIDTH = 960
    TIMEOUT = 1000
    GXF_WAIT_SEC = 10
    FEATNET_ENGINE_FILE_PATH = '/tmp/dummy_bi3dnet_featnet.engine'
    SEGNET_ENGINE_FILE_PATH = '/tmp/dummy_bi3dnet_segnet.engine'

    def _create_image(self, name):
        image = Image()
        image.height = self.IMAGE_HEIGHT
        image.width = self.IMAGE_WIDTH
        image.encoding = 'rgb8'
        image.is_bigendian = False
        image.step = self.IMAGE_WIDTH * 3
        image.data = [0] * self.IMAGE_HEIGHT * self.IMAGE_WIDTH * 3
        image.header.frame_id = name
        return image

    def _create_disparity_value_array(self):
        disp_vals = Bi3DInferenceParametersArray()
        disp_vals.disparity_values = [18]
        return disp_vals

    def test_image_bi3d(self):
        end_time = time.time() + self.TIMEOUT
        while time.time() < end_time:
            if os.path.isfile(self.FEATNET_ENGINE_FILE_PATH) and \
               os.path.isfile(self.SEGNET_ENGINE_FILE_PATH):
                break
        self.assertTrue(os.path.isfile(self.FEATNET_ENGINE_FILE_PATH),
                        'Featnet engine file was not generated in time.')
        self.assertTrue(os.path.isfile(self.SEGNET_ENGINE_FILE_PATH),
                        'Segnet engine file was not generated in time.')

        time.sleep(self.GXF_WAIT_SEC)

        received_messages = {}

        self.generate_namespace_lookup(['left_image_bi3d', 'right_image_bi3d',
                                        'bi3d_disparity_values', 'bi3d_node/bi3d_output'])

        subs = self.create_logging_subscribers(
            [('bi3d_node/bi3d_output', DisparityImage)], received_messages)

        image_left_pub = self.node.create_publisher(
            Image, self.namespaces['left_image_bi3d'], self.DEFAULT_QOS
        )
        image_right_pub = self.node.create_publisher(
            Image, self.namespaces['right_image_bi3d'], self.DEFAULT_QOS
        )
        disparity_values_pub = self.node.create_publisher(
            Bi3DInferenceParametersArray, self.namespaces['bi3d_disparity_values'],
            self.DEFAULT_QOS
        )

        try:
            left_image = self._create_image('left_image')
            right_image = self._create_image('right_image')
            disparity_values = self._create_disparity_value_array()

            end_time = time.time() + self.TIMEOUT
            done = False

            while time.time() < end_time:
                image_left_pub.publish(left_image)
                image_right_pub.publish(right_image)
                disparity_values_pub.publish(disparity_values)

                rclpy.spin_once(self.node, timeout_sec=0.1)

                if 'bi3d_node/bi3d_output' in received_messages:
                    done = True
                    break
            self.assertTrue(done, 'Didnt recieve output on bi3d_node/bi3d_output topic')

            disparity = received_messages['bi3d_node/bi3d_output']
            self.assertEqual(disparity.image.encoding, '32FC1')
            self.assertEqual(disparity.image.height, self.IMAGE_HEIGHT)
            self.assertEqual(disparity.image.width, self.IMAGE_WIDTH)

        finally:
            [self.node.destroy_subscription(sub) for sub in subs]
            self.node.destroy_publisher(image_left_pub)
            self.node.destroy_publisher(image_right_pub)
