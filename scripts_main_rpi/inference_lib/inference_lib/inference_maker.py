import time

from pyrovision.models.rexnet import rexnet1_0x
from torchvision import transforms
import torch
from PIL import Image
import os


class InferenceMaker:
    """Makes the inference on all images in a given folder"""

    def __init__(self, path_to_images_folder):
        self.path_to_images_folder = path_to_images_folder
        self.normalize = transforms.Normalize(
            mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]
        )
        self.img_size = 448
        self.tf = transforms.Compose(
            [
                transforms.Resize(size=self.img_size),
                transforms.CenterCrop(size=self.img_size),
                transforms.ToTensor(),
                self.normalize,
            ]
        )
        self.model = rexnet1_0x(pretrained=True).eval()

    def predict(self, path_to_image_file):
        image = Image.open(path_to_image_file).convert("RGB")
        image_transform = self.tf(image)
        with torch.no_grad():
            pred = self.model(image_transform.unsqueeze(0))
            pred = torch.sigmoid(pred).item()
        if pred < 0.5:
            print("No fire detected. Fire probability: {:.2%}".format(pred))
        else:
            print("Fire detected! Fire probability: {:.2%}".format(pred))

    def get_predictions_for_all_images(self):
        for file in os.listdir(self.path_to_images_folder):
            if file.endswith(".jpg"):
                self.predict(os.path.join(self.path_to_images_folder, file))
                time.sleep(5)


if __name__ == "__main__":
    path_to_images_folder = "/home/pi/images"
    inference_maker = InferenceMaker(path_to_images_folder)
    inference_maker.get_predictions_for_all_images()
