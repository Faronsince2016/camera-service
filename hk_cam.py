import logging
from ctypes import memset, byref, sizeof, cast, c_ubyte, POINTER
from typing import List

import numpy as np
from cv2 import cv2

from MvImport.CameraParams_header import (MV_FRAME_OUT_INFO_EX, MV_CC_DEVICE_INFO, MV_TRIGGER_MODE_OFF, MVCC_INTVALUE,
                                          MV_CC_DEVICE_INFO_LIST, PixelType_Gvsp_RGB8_Packed)
from MvImport.MvCameraControl_class import MvCamera, MV_GIGE_DEVICE, MV_USB_DEVICE, MV_ACCESS_Exclusive

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# logger.info("Start print log")
# logger.debug("Do something")
# logger.warning("Something maybe fail.")
# logger.info("Finish")


class HikCam:
    def __init__(self, camera_index: int):
        self.device_origin_list = MV_CC_DEVICE_INFO_LIST()

        self.camera_list: List = self.get_device_list()
        self.camera = MvCamera()

        self.init_camera_handler(camera_index)
        self.open_camera()
        self.set_trigger_mode(MV_TRIGGER_MODE_OFF)
        # 设置BGR 异常  set PixelFormat fail! ret[0x80000101]
        self.set_pixel_format(PixelType_Gvsp_RGB8_Packed)
        self.payload_size = self.get_payload_size()
        self.start_grabbing()
        self.data_buf = (c_ubyte * self.payload_size)()
        self.data_buf_ref = byref(self.data_buf)
        # frame info
        self.stFrameInfo = MV_FRAME_OUT_INFO_EX()
        memset(byref(self.stFrameInfo), 0, sizeof(self.stFrameInfo))

    def init_camera_handler(self, camera_index: int):
        # ch:选择设备并创建句柄| en:Select device and create handle
        stDeviceList = cast(
            self.device_origin_list.pDeviceInfo[int(camera_index)],
            POINTER(MV_CC_DEVICE_INFO)
        ).contents
        ret = self.camera.MV_CC_CreateHandle(stDeviceList)
        if ret != 0:
            raise RuntimeError('create handle fail! ret[0x%x]' % ret)

    def open_camera(self):
        # ch:打开设备 | en:Open device
        ret = self.camera.MV_CC_OpenDevice(MV_ACCESS_Exclusive, 0)
        if ret != 0:
            raise RuntimeError("open device fail! ret[0x%x]" % ret)

    def set_pixel_format(self, mode: int = PixelType_Gvsp_RGB8_Packed):
        ret = self.camera.MV_CC_SetEnumValue("PixelFormat", mode)
        if ret != 0:
            raise RuntimeError("set PixelFormat fail! ret[0x%x]" % ret)

    def set_trigger_mode(self, mode: int = MV_TRIGGER_MODE_OFF):
        ret = self.camera.MV_CC_SetEnumValue("TriggerMode", mode)
        if ret != 0:
            raise RuntimeError("set trigger mode fail! ret[0x%x]" % ret)

    def get_payload_size(self):
        """
        # ch:获取数据包大小 | en:Get payload size
        :return:
        """
        stParam = MVCC_INTVALUE()
        memset(byref(stParam), 0, sizeof(MVCC_INTVALUE))
        ret = self.camera.MV_CC_GetIntValue("PayloadSize", stParam)
        if ret != 0:
            logger.error("get payload size fail! ret[0x%x]" % ret)
            raise
        return stParam.nCurValue

    def start_grabbing(self):
        """
        ch:开始取流 | en:Start grab image
        :return:
        """
        ret = self.camera.MV_CC_StartGrabbing()
        if ret != 0:
            raise RuntimeError("start grabbing fail! ret[0x%x]" % ret)

    def stop_grabbing(self):
        # ch:停止取流 | en:Stop grab image
        ret = self.camera.MV_CC_StopGrabbing()
        if ret != 0:
            logger.error("stop grabbing fail! ret[0x%x]" % ret)
            self.data_buf = None
            raise

    def destroy_handler(self):
        # ch:销毁句柄 | Destroy handle
        ret = self.camera.MV_CC_DestroyHandle()
        if ret != 0:
            print("destroy handle fail! ret[0x%x]" % ret)
            self.data_buf = None
            raise

    def close_camera(self):
        ret = self.camera.MV_CC_CloseDevice()
        if ret != 0:
            logger.error("close deivce fail! ret[0x%x]" % ret)
            self.data_buf = None
            raise

    def detect_packet_size(self):
        """
        for GigE
        ch:探测网络最佳包大小(只对GigE相机有效)
        :return:
        """
        nPacketSize = self.camera.MV_CC_GetOptimalPacketSize()
        if int(nPacketSize) > 0:
            ret = self.camera.MV_CC_SetIntValue("GevSCPSPacketSize", nPacketSize)
            if ret != 0:
                logger.warning("Warning: Set Packet Size fail! ret[0x%x]" % ret)
        else:
            logger.warning("Warning: Set Packet Size fail! ret[0x%x]" % nPacketSize)

    def get_device_list(self):
        nTLayerType = MV_GIGE_DEVICE | MV_USB_DEVICE
        # ch:枚举设备 | en:Enum device
        enum_ret = MvCamera.MV_CC_EnumDevices(nTLayerType, self.device_origin_list)
        if enum_ret or not self.device_origin_list.nDeviceNum:
            raise RuntimeError(f'enum devices fail or find no device! {enum_ret}')

        device_result_list = []
        for i in range(0, self.device_origin_list.nDeviceNum):
            dev_result_info = dict(index=i, dev_name='', ip='', sn='', device_type='')
            device_origin_info = cast(self.device_origin_list.pDeviceInfo[i], POINTER(MV_CC_DEVICE_INFO)).contents
            if device_origin_info.nTLayerType == MV_GIGE_DEVICE:
                dev_result_info['device_type'] = 'GigE'
                # fetch device name
                for per in device_origin_info.SpecialInfo.stGigEInfo.chModelName:
                    dev_result_info["dev_name"] = dev_result_info["dev_name"] + chr(per)
                # fetch ip
                nCurrentIp = device_origin_info.SpecialInfo.stGigEInfo.nCurrentIp
                nip1 = ((nCurrentIp & 0xff000000) >> 24)
                nip2 = ((nCurrentIp & 0x00ff0000) >> 16)
                nip3 = ((nCurrentIp & 0x0000ff00) >> 8)
                nip4 = (nCurrentIp & 0x000000ff)
                dev_result_info['ip'] = f"{nip1},{nip2},{nip3},{nip4}"
                device_result_list.append(dev_result_info)
            elif device_origin_info.nTLayerType == MV_USB_DEVICE:
                dev_result_info['device_type'] = 'USB3V'
                for per in device_origin_info.SpecialInfo.stUsb3VInfo.chModelName:
                    if per == 0:
                        break
                    dev_result_info["dev_name"] = dev_result_info["dev_name"] + chr(per)
                for per in device_origin_info.SpecialInfo.stUsb3VInfo.chSerialNumber:
                    if per == 0:
                        break
                    dev_result_info["sn"] = dev_result_info["sn"] + chr(per)
                device_result_list.append(dev_result_info)

        return device_result_list

    @property
    def get_sdk_info(self):
        return MvCamera.MV_CC_GetSDKVersion()

    def get_frame_once(self):
        # 313 ms
        ret = self.camera.MV_CC_GetOneFrameTimeout(self.data_buf_ref, self.payload_size, self.stFrameInfo, 1000)

        if ret == 0:
            # logger.info("get one frame: Width[%d], Height[%d], PixelType[0x%x], nFrameNum[%d]" % (
            #     self.stFrameInfo.nWidth, self.stFrameInfo.nHeight,
            #     self.stFrameInfo.enPixelType, self.stFrameInfo.nFrameNum))
            #  40ms
            frame_data = np.asarray(self.data_buf)
            image = frame_data.reshape((self.stFrameInfo.nHeight, self.stFrameInfo.nWidth, 3))
            image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

            return image
        else:
            logger.error("no data[0x%x]" % ret)


if __name__ == '__main__':
    cam = HikCam(0)
    one_frame = cam.get_frame_once()
    cv2.imwrite('ttt2.jpg', one_frame)
