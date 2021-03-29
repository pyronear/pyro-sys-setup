import time

from watchdog.observers import Observer

from .images_handler import ImagesHandler
from .inference_maker import InferenceMaker


class ImagesWatcher:
    """Watcher for new files in scr_path"""

    def __init__(self, src_path, event_handler):
        self.src_path = src_path
        self.event_handler = event_handler
        self.observer = Observer()

    def run(self):
        self.observer.schedule(self.event_handler, self.src_path, recursive=True)
        self.observer.start()
        try:
            while True:
                time.sleep(5)
        except Exception as e:
            self.observer.stop()
            print("Error: ", repr(e))
        self.observer.join()


if __name__ == "__main__":
    src_path = "/home/pi/images"
    inference_maker = InferenceMaker(src_path)
    event_handler = ImagesHandler(inference_maker)
    watcher = ImagesWatcher(src_path, event_handler)
    watcher.run()
