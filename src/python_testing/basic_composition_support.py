#
#    Copyright (c) 2023 Project CHIP Authors
#    All rights reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.
#


import base64
import copy
import json
import logging
import pathlib
import sys
from pprint import pprint
from typing import Any, Optional

import chip.clusters.ClusterObjects
import chip.tlv
from chip.clusters.Attribute import ValueDecodeFailure
from mobly import asserts


def MatterTlvToJson(tlv_data: dict[int, Any]) -> dict[str, Any]:
    """Given TLV data for a specific cluster instance, convert to the Matter JSON format."""

    matter_json_dict = {}

    key_type_mappings = {
        chip.tlv.uint: "UINT",
        int: "INT",
        bool: "BOOL",
        list: "ARRAY",
        dict: "STRUCT",
        chip.tlv.float32: "FLOAT",
        float: "DOUBLE",
        bytes: "BYTES",
        str: "STRING",
        ValueDecodeFailure: "ERROR",
        type(None): "NULL",
    }

    def ConvertValue(value) -> Any:
        if isinstance(value, ValueDecodeFailure):
            raise ValueError(f"Bad Value: {str(value)}")

        if isinstance(value, bytes):
            return base64.b64encode(value).decode("UTF-8")
        elif isinstance(value, list):
            value = [ConvertValue(item) for item in value]
        elif isinstance(value, dict):
            value = MatterTlvToJson(value)

        return value

    for key in tlv_data:
        value_type = type(tlv_data[key])
        value = copy.deepcopy(tlv_data[key])

        element_type: str = key_type_mappings[value_type]
        sub_element_type = ""

        try:
            new_value = ConvertValue(value)
        except ValueError as e:
            new_value = str(e)

        if element_type:
            if element_type == "ARRAY":
                if len(new_value):
                    sub_element_type = key_type_mappings[type(tlv_data[key][0])]
                else:
                    sub_element_type = "?"

        new_key = ""
        if element_type:
            if sub_element_type:
                new_key = f"{str(key)}:{element_type}-{sub_element_type}"
            else:
                new_key = f"{str(key)}:{element_type}"
        else:
            new_key = str(key)

        matter_json_dict[new_key] = new_value

    return matter_json_dict


class BasicCompositionTests:
    async def setup_class_helper(self):
        dev_ctrl = self.default_controller
        self.problems = []

        do_test_over_pase = self.user_params.get("use_pase_only", True)
        dump_device_composition_path: Optional[str] = self.user_params.get("dump_device_composition_path", None)

        if do_test_over_pase:
            info = self.get_setup_payload_info()

            commissionable_nodes = dev_ctrl.DiscoverCommissionableNodes(
                info.filter_type, info.filter_value, stopOnFirst=True, timeoutSecond=15)
            logging.info(f"Commissionable nodes: {commissionable_nodes}")
            # TODO: Support BLE
            if commissionable_nodes is not None and len(commissionable_nodes) > 0:
                commissionable_node = commissionable_nodes[0]
                instance_name = f"{commissionable_node.instanceName}._matterc._udp.local"
                vid = f"{commissionable_node.vendorId}"
                pid = f"{commissionable_node.productId}"
                address = f"{commissionable_node.addresses[0]}"
                logging.info(f"Found instance {instance_name}, VID={vid}, PID={pid}, Address={address}")

                node_id = 1
                dev_ctrl.EstablishPASESessionIP(address, info.passcode, node_id)
            else:
                asserts.fail("Failed to find the DUT according to command line arguments.")
        else:
            # Using the already commissioned node
            node_id = self.dut_node_id

        wildcard_read = (await dev_ctrl.Read(node_id, [()]))
        endpoints_tlv = wildcard_read.tlvAttributes

        node_dump_dict = {endpoint_id: MatterTlvToJson(endpoints_tlv[endpoint_id]) for endpoint_id in endpoints_tlv}
        logging.debug(f"Raw TLV contents of Node: {json.dumps(node_dump_dict, indent=2)}")

        if dump_device_composition_path is not None:
            with open(pathlib.Path(dump_device_composition_path).with_suffix(".json"), "wt+") as outfile:
                json.dump(node_dump_dict, outfile, indent=2)
            with open(pathlib.Path(dump_device_composition_path).with_suffix(".txt"), "wt+") as outfile:
                pprint(wildcard_read.attributes, outfile, indent=1, width=200, compact=True)

        logging.info("###########################################################")
        logging.info("Start of actual tests")
        logging.info("###########################################################")

        # ======= State kept for use by all tests =======

        # All endpoints in "full object" indexing format
        self.endpoints = wildcard_read.attributes

        # All endpoints in raw TLV format
        self.endpoints_tlv = wildcard_read.tlvAttributes

    def get_test_name(self) -> str:
        """Return the function name of the caller. Used to create logging entries."""
        return sys._getframe().f_back.f_code.co_name

    def fail_current_test(self, msg: Optional[str] = None):
        if not msg:
            # Without a message, just log the last problem seen
            asserts.fail(msg=self.problems[-1].problem)
        else:
            asserts.fail(msg)
