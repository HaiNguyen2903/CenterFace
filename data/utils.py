import cv2
import numpy as np
import torch
import random 

class AverageMeter(object):
    """Computes and stores the average and current value"""
    def __init__(self):
        self.reset()

    def reset(self):
        self.val = 0
        self.avg = 0
        self.sum = 0
        self.count = 0

    def update(self, val, n=1):
        self.val = val
        self.sum += val * n
        self.count += n
        if self.count > 0:
          self.avg = self.sum / self.count


def Data_anchor_sample(image, anns):
    '''
    This function use to random scale image and anns ? 
    This function take image and anns of objects as input and return new image and new anns for objects
    '''
    maxSize = 12000
    infDistance = 9999999

    boxes = []
    for ann in anns:
        boxes.append([ann['bbox'][0], ann['bbox'][1], ann['bbox'][0]+ann['bbox'][2], ann['bbox'][1]+ann['bbox'][3]])
    boxes = np.asarray(boxes, dtype=np.float32)

    height, width, _ = image.shape
    # print('height: {}, width: {}'.format(height, width))

    random_counter = 0

    boxArea = (boxes[:, 2] - boxes[:, 0] + 1) * (boxes[:, 3] - boxes[:, 1] + 1)
    rand_idx = random.randint(0, len(boxArea)-1)
    rand_Side = boxArea[rand_idx] ** 0.5

    anchors = [16, 32, 48, 64, 96, 128, 256, 512]
    distance = infDistance
    anchor_idx = 5
    for i, anchor in enumerate(anchors):
        if abs(anchor - rand_Side) < distance:
            distance = abs(anchor - rand_Side)  # 选择最接近的anchors       Choose the closet anchor
            anchor_idx = i

    target_anchor = random.choice(anchors[0:min(anchor_idx+1, 5) ])  # 随机选择一个相对较小的anchor，向下       Randomly select a relatively small anchor, down
    ratio = float(target_anchor) / rand_Side  # 缩放的尺度      Scale of scaling
    ratio = ratio * (2 ** random.uniform(-1, 1))  # [ratio/2, 2ratio]的均匀分布     Uniform distribution

    if int(height * ratio * width * ratio) > maxSize * maxSize:
        ratio = (maxSize * maxSize / (height * width)) ** 0.5

    interp_methods = [cv2.INTER_LINEAR, cv2.INTER_CUBIC, cv2.INTER_AREA, cv2.INTER_NEAREST, cv2.INTER_LANCZOS4]
    interp_method = random.choice(interp_methods)
    image = cv2.resize(image, None, None, fx=ratio, fy=ratio, interpolation=interp_method)

    boxes[:, 0] *= ratio
    boxes[:, 1] *= ratio
    boxes[:, 2] *= ratio
    boxes[:, 3] *= ratio

    boxes = boxes.tolist()
    for i in range(len(anns)):
        anns[i]['bbox'] = [boxes[i][0], boxes[i][1], boxes[i][2]-boxes[i][0], boxes[i][3]-boxes[i][1]]      # 人脸bbox   face bboxes
        for j in range(5):
            anns[i]['keypoints'][j*3] *= ratio
            anns[i]['keypoints'][j*3+1] *= ratio

    return image, anns


def gaussian_radius(det_size, min_overlap=0.7):
    '''
    Follow explantion from https://zhuanlan.zhihu.com/p/96856635, this function is used to find out a radius circle 
    for gaussian kernel. Basically, if the IoU of GT and predicted box is >= a threshold (0.7 for example), it's not set
    to 0 directly. 
    This function take det_size (image shape ?) and IoU threshold as input and return the expected circle radius
    '''
    height, width = det_size

    a1  = 1
    b1  = (height + width)
    c1  = width * height * (1 - min_overlap) / (1 + min_overlap)
    sq1 = np.sqrt(b1 ** 2 - 4 * a1 * c1)
    r1  = (b1 + sq1) / 2

    a2  = 4
    b2  = 2 * (height + width)
    c2  = (1 - min_overlap) * width * height
    sq2 = np.sqrt(b2 ** 2 - 4 * a2 * c2)
    r2  = (b2 + sq2) / 2

    a3  = 4 * min_overlap
    b3  = -2 * min_overlap * (height + width)
    c3  = (min_overlap - 1) * width * height
    sq3 = np.sqrt(b3 ** 2 - 4 * a3 * c3)
    r3  = (b3 + sq3) / 2
    return min(r1, r2, r3)


def gaussian2D(shape, sigma=1):
    m, n = [(ss - 1.) / 2. for ss in shape]
    y, x = np.ogrid[-m:m+1,-n:n+1]

    h = np.exp(-(x * x + y * y) / (2 * sigma * sigma))
    h[h < np.finfo(h.dtype).eps * h.max()] = 0
    return h


def draw_umich_gaussian(heatmap, center, radius, k=1):
    '''
    Draw 
    '''
    diameter = 2 * radius + 1                                         # Get diameter
    gaussian = gaussian2D((diameter, diameter), sigma=diameter / 6)
    
    x, y = int(center[0]), int(center[1])

    height, width = heatmap.shape[0:2]
        
    left, right = min(x, radius), min(width - x, radius + 1)
    top, bottom = min(y, radius), min(height - y, radius + 1)

    masked_heatmap  = heatmap[y - top:y + bottom, x - left:x + right]         # Assign a value to that area
    masked_gaussian = gaussian[radius - top:radius + bottom, radius - left:radius + right]
    if min(masked_gaussian.shape) > 0 and min(masked_heatmap.shape) > 0: # TODO debug
        np.maximum(masked_heatmap, masked_gaussian * k, out=masked_heatmap)
    return heatmap


def draw_dense_reg(regmap, heatmap, center, value, radius, is_offset=False):
    diameter = 2 * radius + 1
    gaussian = gaussian2D((diameter, diameter), sigma=diameter / 6)
    value = np.array(value, dtype=np.float32).reshape(-1, 1, 1)
    dim = value.shape[0]
    reg = np.ones((dim, diameter*2+1, diameter*2+1), dtype=np.float32) * value
    if is_offset and dim == 2:
        delta = np.arange(diameter*2+1) - radius
        reg[0] = reg[0] - delta.reshape(1, -1)
        reg[1] = reg[1] - delta.reshape(-1, 1)
    
    x, y = int(center[0]), int(center[1])

    height, width = heatmap.shape[0:2]
        
    left, right = min(x, radius), min(width - x, radius + 1)
    top, bottom = min(y, radius), min(height - y, radius + 1)

    masked_heatmap = heatmap[y - top:y + bottom, x - left:x + right]
    masked_regmap = regmap[:, y - top:y + bottom, x - left:x + right]
    masked_gaussian = gaussian[radius - top:radius + bottom,
                                radius - left:radius + right]
    masked_reg = reg[:, radius - top:radius + bottom,
                        radius - left:radius + right]
    if min(masked_gaussian.shape) > 0 and min(masked_heatmap.shape) > 0: # TODO debug
        idx = (masked_gaussian >= masked_heatmap).reshape(
        1, masked_gaussian.shape[0], masked_gaussian.shape[1])
        masked_regmap = (1-idx) * masked_regmap + idx * masked_reg
    regmap[:, y - top:y + bottom, x - left:x + right] = masked_regmap
    return regmap


def draw_msra_gaussian(heatmap, center, sigma):
    tmp_size = sigma * 3
    mu_x = int(center[0] + 0.5)
    mu_y = int(center[1] + 0.5)
    w, h = heatmap.shape[0], heatmap.shape[1]
    ul = [int(mu_x - tmp_size), int(mu_y - tmp_size)]
    br = [int(mu_x + tmp_size + 1), int(mu_y + tmp_size + 1)]
    if ul[0] >= h or ul[1] >= w or br[0] < 0 or br[1] < 0:
        return heatmap
    size = 2 * tmp_size + 1
    x = np.arange(0, size, 1, np.float32)
    y = x[:, np.newaxis]
    x0 = y0 = size // 2
    g = np.exp(- ((x - x0) ** 2 + (y - y0) ** 2) / (2 * sigma ** 2))
    g_x = max(0, -ul[0]), min(br[0], h) - ul[0]
    g_y = max(0, -ul[1]), min(br[1], w) - ul[1]
    img_x = max(0, ul[0]), min(br[0], h)
    img_y = max(0, ul[1]), min(br[1], w)
    heatmap[img_y[0]:img_y[1], img_x[0]:img_x[1]] = np.maximum(
        heatmap[img_y[0]:img_y[1], img_x[0]:img_x[1]],
        g[g_y[0]:g_y[1], g_x[0]:g_x[1]])
    return heatmap