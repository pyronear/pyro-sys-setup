from inference_lib.images_handler import ImagesHandler
from inference_lib.images_watcher import ImagesWatcher
from inference_lib.inference_maker import InferenceMaker

if __name__ == "__main__":
    src_path = "/home/pi/images"
    inference_maker = InferenceMaker(src_path)
    # event_handler = ImagesHandler(inference_maker)
    # watcher = ImagesWatcher(src_path, event_handler)
    # watcher.run()
    while True:
        inference_maker.get_predictions_for_all_images()
