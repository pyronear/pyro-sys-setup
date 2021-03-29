from watchdog.events import RegexMatchingEventHandler


class ImagesHandler(RegexMatchingEventHandler):
    IMAGES_REGEX = [r"image.+\.jpg$"]

    def __init__(self, inference_maker):
        super().__init__(self.IMAGES_REGEX)
        self.inference_maker = inference_maker

    def on_created(self, event):
        self.process(event)

    def process(self, event):
        print("Get inference for:", event.src_path)
        self.inference_maker.predict(event.src_path)
