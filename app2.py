import asyncio
import base64
import threading
import time
import uuid
from abc import ABC
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy
import tornado
import tornado.httpserver
import tornado.ioloop
import tornado.web
import tornado.websocket

# 使用camera index获取相机
from hk_cam import HikCam

capture_event = threading.Event()
origin_frame = None
push_frame = b''
frame_id = 0
MAX_FPS = 20
CACHE_PATH = '/tmp'


def gen_uuid():
    uuid_origin = uuid.uuid4()
    uuid_str = str(uuid_origin).replace('-', '')
    return uuid_str


class BaseHandler(tornado.web.RequestHandler, ABC):
    def set_default_headers(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS, DELETE, PUT')
        self.set_header("Access-Control-Allow-Headers", "token, content-type, user-token")


class HTTP(BaseHandler, ABC):
    def get(self):
        self.render('./index.html')


class FrameHandler(BaseHandler, ABC):

    def get(self):
        global origin_frame
        mode = self.get_argument('mode')
        if mode == 'path':
            img_path = Path(CACHE_PATH).joinpath('test.jpg')
            if capture_event.is_set():
                img = origin_frame
            else:
                img = camera.get_frame_once()
            cv2.imwrite(img_path.as_posix(), img)
            # 使用nginx保证图片能通过url访问
            self.write(dict(path=img_path.as_posix(), url=f'http://localhost:8880/{img_path.name}'))
        elif mode == 'base64':
            self.write(dict(path='', url=push_frame))
        else:
            self.write_error(status_code=403)


class CamParamsHandler(BaseHandler, ABC):

    def get(self):
        """
        :return: 获取当前相机的所有参数，并获取所有可修改值
        """
        camera_params = dict(
            width=5472,
            height=3648,
        )
        self.write(camera_params)

    def post(self):
        """
        从配置文件中加载参数并设置到相机中
        :return:
        """

    def put(self):
        """
        参数设置,当参数不可设置时回写错误
        :return:
        """
        self.write('22222')

    def delete(self):
        """
        相机参数恢复默认值
        :return:
        """


class StreamWebSocket(tornado.websocket.WebSocketHandler, ABC):
    WS_SET = set()

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.ws_connection_closed = False
        self.pushed_frame_id = 1

    def initialize(self):
        print('initialize')

    def check_origin(self, origin):
        # 允许WebSocket的跨域请求
        return True

    def open(self):
        global push_frame, frame_id
        print('{0}:connection open'.format(self.request.remote_ip))
        StreamWebSocket.WS_SET.add(self)
        print(self.request.connection.context.address)
        capture_event.set()
        print('start rec...')

    async def on_message(self, message):
        global push_frame, frame_id

        while True:
            time.sleep(1 / MAX_FPS)
            if frame_id != self.pushed_frame_id:
                break
        self.pushed_frame_id = frame_id
        if capture_event.is_set():
            try:
                fut = self.write_message(push_frame)
                await fut
            except tornado.iostream.StreamClosedError as e:
                print('StreamClosedError:', e)
            except tornado.websocket.WebSocketClosedError as e:
                print('WebSocketClosedError:', e)

    def on_ws_connection_close(self, close_code: Optional[int] = None, close_reason: Optional[str] = None) -> None:
        StreamWebSocket.WS_SET.remove(self)
        self.close()
        if not StreamWebSocket.WS_SET:
            # 当所有ws断开后才能关闭capture
            capture_event.clear()
        print(f'{self.request.remote_ip}:ws connection close')


def start_server(server):
    asyncio.set_event_loop(asyncio.new_event_loop())
    server.run()


def start_capture():
    global origin_frame, push_frame, frame_id
    while True:
        try:
            capture_event.wait()
            origin_frame = camera.get_frame_once()
            # img = cv2.imencode('.jpeg', origin_frame)[1].tobytes()
            # push_frame = (b'--frame\r\n'
            #               b'Content-Type: image/jpeg\r\n\r\n' + img + b'\r\n')
            image = cv2.imencode('.jpg', origin_frame)[1]
            image = numpy.array(image).tobytes()
            push_frame = base64.b64encode(image)
            frame_id = gen_uuid()
        except Exception as e:
            print(e)


def thread_is_alive(WORK_THREADS):
    while True:
        if WORK_THREADS and False in [t.is_alive() for t in WORK_THREADS]:
            raise RuntimeError('Thread Error!')
        time.sleep(1)


class WebServer(tornado.web.Application):

    def __init__(self):
        handlers = [
            ('/', HTTP),
            ('/live', StreamWebSocket),
            ('/param', CamParamsHandler),
            ('/frame', FrameHandler)
        ]
        settings = {'debug': False}
        super().__init__(handlers, **settings)

    def run(self, port=8888):
        self.listen(port)
        tornado.ioloop.IOLoop.instance().start()


if __name__ == '__main__':
    global camera
    camera = HikCam(0)
    web_server = WebServer()
    work_threads = [threading.Thread(target=start_server, args=(web_server,)),
                    threading.Thread(target=start_capture, args=())]
    for thread in work_threads:
        thread.setDaemon(True)
        thread.start()
    thread_is_alive(work_threads)
