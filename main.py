import os

import cv2
import matplotlib.pyplot as plt
import numpy as np

from tensorflow.keras.applications.vgg16 import VGG16
from tensorflow.keras.layers import Input

from OCR import perform_class_OCR
from evaluateModel import init_evaluation_data, calculate_average_metrics
from train_class import load_svm
from train_relationship import load_svm_relationship
from generate_code import Class, add_relationship, make_project


def load_image(path):
    return cv2.imread(path)


def resize_image(image):
    return cv2.resize(image, (1024, 576), interpolation=cv2.INTER_NEAREST)


def image_gray(image):
    return cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)


def image_bin(image_gs):
    height, width = image_gs.shape[0:2]
    image_binary = np.ndarray((height, width), dtype=np.uint8)
    ret, image_bin = cv2.threshold(image_gs, 127, 255, cv2.THRESH_BINARY)
    return image_bin


def image_bin_sobel(image_sobel, avg_value, max_value):
    height, width = image_sobel.shape[0:2]
    image_binary = np.ndarray((height, width), dtype=np.uint8)
    ret, image_bin = cv2.threshold(image_sobel, avg_value, max_value, cv2.THRESH_BINARY)
    return image_bin


def dilate(image):
    kernel = np.ones((3, 3))  # strukturni element 3x3 blok
    return cv2.dilate(image, kernel, iterations=1)


def erode(image):
    kernel = np.ones((2, 2))  # strukturni element 3x3 blok
    return cv2.erode(image, kernel, iterations=2)


def select_roi_class(image_orig, image_bin):
    contours, hierarchy = cv2.findContours(image_bin.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    regions_array = []

    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w > 100 or h > 100:
            region = image_orig[y:y + h + 1, x:x + w + 1]
            regions_array.append([region, (x, y, w, h)])
            # cv2.rectangle(image_orig, (x, y), (x + w, y + h), (0, 255, 0), 5)

    regions_array = sorted(regions_array, key=lambda x: x[1][0])
    # plt.imshow(image_orig)
    # plt.show()

    index = 0
    while index < len(regions_array):
        current = regions_array[index]
        for idx in range(index + 1, len(regions_array)):
            next_rect = regions_array[idx]

            result = 0
            x, y, w, h = current[1]
            x1, y1, w1, h1 = next_rect[1]
            height = max(h, h1, w, w1) * 0.5

            if y < y1 and y + h + height < y1:
                continue
            elif y > y1 and y1 + h1 + height < y:
                continue
            elif w < w1:
                result = line_matching(next_rect[1], current[1]) / w1
            else:
                result = line_matching(current[1], next_rect[1]) / w

            # spajanje dva region ako se njihova sirina preklapa 0.8 i dovoljno je blizu
            if result > 0.7:
                x2 = min(x, x1)
                y2 = min(y, y1)
                w2 = max(x + w, x1 + w1) - x2
                h2 = max(y + h, y1 + h1) - y2
                region = image_orig[y2:y2 + h2 + 1, x2:x2 + w2 + 1]
                regions_array[index] = [region, (x2, y2, w2, h2)]
                del regions_array[idx]
                break
        else:
            index += 1

    # da se sklone horizontalne veze koje su upale
    # regions = []
    # for region in regions_array:
    #     x, y, w, h = region[1]
    #     if w * 3 > h and h * 3 > w:
    #         regions.append(region)
    return regions_array


def line_matching(bigger, smaller):
    if bigger[0] <= smaller[0] and bigger[0] + bigger[2] >= smaller[0] + smaller[2]:
        return smaller[2]
    elif bigger[0] <= smaller[0]:
        return bigger[0] + bigger[2] - smaller[0]
    elif bigger[0] + bigger[2] >= smaller[0] + smaller[2]:
        return smaller[0] + smaller[2] - bigger[0]
    else:
        return 0


def performSobel(image, direction="horizontal", line_size=31):
    img_gs = image_gray(image)
    if direction == "horizontal":
        sobelx64f = cv2.Sobel(img_gs, cv2.CV_64F, 0, 1, ksize=line_size)
    else:
        sobelx64f = cv2.Sobel(img_gs, cv2.CV_64F, 1, 0, ksize=line_size)

    sobelx64f = np.abs(sobelx64f)

    sobelx64f = dilate(sobelx64f)
    sobelx64f = dilate(sobelx64f)
    sobelx64f = erode(sobelx64f)

    sobelx64f = erode(sobelx64f)
    # sobelx64f = erode(sobelx64f)
    # make binary images from sobel transformed images
    sobelx64f_bin = image_bin_sobel(sobelx64f, np.average(sobelx64f) * 2.4, np.max(sobelx64f))

    sobelx64f_bin = sobelx64f_bin / np.max(sobelx64f_bin)
    sobelxUint8 = np.asarray(sobelx64f_bin, dtype=np.uint8)

    plt.imshow(sobelxUint8, 'gray')
    plt.show()
    return sobelxUint8


def findRelationShipsRegions(resized_image, direction="horizontal"):
    sobelxUint8 = performSobel(resized_image, direction)
    regions = select_roi_class(resized_image, sobelxUint8)

    # boje da bude recnik kasnije da uzimas sta ti treba...
    # for region in sorted_regions:
    #   region.append(direction)

    return regions


def resize_region_cnn(region):
    height, width, depth = region.shape
    max_dim = max(height, width)
    max_dim_img = np.zeros([max_dim, max_dim, 3], dtype=np.uint)
    max_dim_img.fill(255)
    # preslikas u gornji levi ugao celu ulaznu sliku, ostalo je crno
    # da li ce to crno da utice na to da on predvidi klasu? a jbg nzm..
    # nisam ga tako trenirao nego onako da iseze i to sto je isekao
    # da resize iz mozda mora ovako da se istrenirao
    for h in range(0, len(region)):
        for w in range(0, len(region[h])):
            max_dim_img[h][w] = region[h][w]
    return cv2.resize(max_dim_img, (224, 224), interpolation=cv2.INTER_NEAREST)


def find_relationships(resized_image, class_array):
    model_rs = load_svm_relationship()
    base_model_relationship = VGG16(weights='imagenet', include_top=False,
                                    input_tensor=Input(shape=(300, 300, 3)),
                                    input_shape=(300, 300, 3))
    for idx in range(0, len(class_array) - 1):
        x, y, w, h = class_array[idx].img[1]
        for i in range(idx + 1, len(class_array)):
            rot = False
            x1, y1, w1, h1 = class_array[i].img[1]
            if abs(x - x1) > abs(y - y1) and (y + h < y1 or y1 + h1 < y):
                continue
            elif abs(x - x1) <= abs(y - y1) and (x + w < x1 or x1 + w1 < x):
                continue
            elif abs(x - x1) > abs(y - y1):
                y2 = min(y, y1)
                h2 = max(y + h, y1 + h1) - y2
                if x < x1:
                    x2 = int(x + w * 0.8)
                    w2 = int(x1 + w1 * 0.2 - x2)
                else:
                    x2 = int(x1 + w1 * 0.8)
                    w2 = int(x + w * 0.2 - x2)
            else:
                x2 = min(x, x1)
                w2 = max(x + w, x1 + w1) - x2
                if y < y1:
                    y2 = int(y + h * 0.8)
                    h2 = int(y1 + h1 * 0.2 - y2)
                else:
                    y2 = int(y1 + h1 * 0.8)
                    h2 = int(y + h * 0.2 - y2)
                rot = True

            region = resized_image[y2:y2 + h2 + 1, x2:x2 + w2 + 1]
            resized_region = cv2.resize(region, (300, 300), interpolation=cv2.INTER_NEAREST)

            if rot:
                (h, w) = resized_region.shape[:2]
                center = (w / 2, h / 2)
                M = cv2.getRotationMatrix2D(center, 90, 1.0)
                resized_region = cv2.warpAffine(resized_region, M, (h, w))

            plt.imshow(resized_region)
            plt.show()

            a = np.asarray([resized_region])

            features = base_model_relationship.predict(a, batch_size=32, verbose=1)
            features = features.reshape((features.shape[0], 512 * 9 * 9))
            max_score = max(model_rs.predict_proba(features)[0])
            scores = model_rs.predict(features)
            print(max_score)
            print(scores)
            if (max_score < 0.5):
                print("veza nije dodata jer score manji od 0.5")
                continue
            print("scores: ", scores)
            if rot and y1 < y:
                add_relationship(scores, class_array[i], class_array[idx])
            else:
                r = add_relationship(scores, class_array[idx], class_array[i])
            # max_score = np.max(scores[0])
            # max_score_indx = np.argmax(scores[0])
            # print(max_score_indx)
            # print(scores)


def show_test_statistic(path):

    # skip_names = ["onlineTool3", "dp7", "dc3"]
    skip_names=[]

    all_similarity_metrics = []
    dirs = os.listdir(path)

    for file in dirs:
        endName = file.index(".")
        img_name = file[0: endName]

        if img_name in skip_names:
            continue

        evaluationMatricData = init_evaluation_data("dataset/test/groundTruth/ground_truth_" + img_name + ".txt")

        img = load_image('dataset/test/images/' + img_name + '.jpg')
        class_array = generate_from_image(img, img_name)

        evaluationMatricData.set_generated_classes(class_array)
        evaluationMatricData.calculate_similarity()
        all_similarity_metrics.append(evaluationMatricData)

    #da izracuna prosecne metrike na celom test skupu
    calculate_average_metrics(all_similarity_metrics)


def generate_from_image(img, img_name):
    base_model = VGG16(weights='imagenet', include_top=False,
                       input_tensor=Input(shape=(224, 224, 3)),
                       input_shape=(224, 224, 3))
    svm = load_svm()
    print(len(img), len(img[0]))
    resized_image = resize_image(img)
    regions_horizontal = findRelationShipsRegions(resized_image, "horizontal")

    # mozes da prodjes kroz sve njih i da ih guras kroz mrezu, one koje klasifikuje kao
    # kao uzmes i dodas ih u recnik..
    # posle proveris da li su povezani sa nekim klasama koje su u recniku..
    # ako nisu onda ih izbacis. ---> ostaje ti da odredis smer veze.. i da poboljsas mrezu
    # kad klasifikuje veze.

    class_array = []
    n = 1
    print(len(regions_horizontal))
    for region in regions_horizontal:
        resized = cv2.resize(region[0], (224, 224), interpolation=cv2.INTER_AREA)
        to_predict = np.asarray([resized], dtype=np.float32) / 255.0

        features = base_model.predict(to_predict)
        features = features.reshape((features.shape[0], 512 * 7 * 7))
        scores = svm.predict_proba(features)[0]

        # plt.imshow(region[0])
        # plt.show()
        # print(scores)
        # 2.5 * da bi radilio za slike koje su paint
        if scores[1] * 2.5 >= scores[0]:
            c = perform_class_OCR(region, n)
            class_array.append(c)
            n += 1

    find_relationships(resized_image, class_array)

    print("******************************")
    for img in class_array:
        print(img.name)
        for i in img.relationships:
            print(i.type)
        # print(img.relationships)
    print("******************************")

    make_project("./generated", img_name, class_array)
    return class_array

if __name__ == '__main__':

    #ovo je za statistkigu nad trening skupom
    path = "dataset/test/images"
    show_test_statistic(path)

    #ovo je kad hocemo da generisemo
    # img_name = "dp4"
    # image_path = 'dataset/test/' + img_name + '.jpg'
    # img = load_image(image_path)
    # class_array = generate_from_image(img, img_name)



