import numpy as np
from skimage import io
from skimage import img_as_ubyte
from skimage import img_as_int
import mahotas
import scipy.ndimage as ndimage
import json
from collections import defaultdict
import os
import skimage.external.tifffile as tifffile

glomeruli_minrad = 15
glomeruli_maxrad = 65

def normalize(img, per=100, min_signal_value=0):
    ph = np.percentile(img, per)
    pl = np.percentile(img, 100 - per)
    if ph > min_signal_value:
        img = np.where(img > ph, ph, img)
        img = np.where(img < pl, pl, img)
        img = img - img.min()
        img = img * 255. / img.max()

    else:
        img = np.zeros_like(img)

    return img


def segment_tissue2d(input_file, output_file, voxel_xy):
    # load image
    img = io.imread(input_file)

    # normalize image
    img = ndimage.median_filter(img, 3)
    img = img * 255. / img.max()

    ##segment kidney tissue

    sizefactor = 10.
    small = ndimage.interpolation.zoom(img, 1. / sizefactor)  # scale the image to a smaller size

    imgf = ndimage.gaussian_filter(small, 3. / voxel_xy)  # Gaussian filter
    median = np.percentile(imgf, 40)  # 40-th percentile for thresholding

    kmask = imgf > median * 1.5  # thresholding
    kmask = mahotas.dilate(kmask, mahotas.disk(5))
    kmask = mahotas.close_holes(kmask)  # closing holes
    kmask = mahotas.erode(kmask, mahotas.disk(5)) * 255

    # remove objects that are darker than 2*percentile
    l, n = ndimage.label(kmask)
    llist = np.unique(l)
    if len(llist) > 2:
        means = ndimage.mean(imgf, l, llist)
        bv = llist[np.where(means < median * 2)]
        ix = np.in1d(l.ravel(), bv).reshape(l.shape)
        kmask[ix] = 0

    kmask = ndimage.interpolation.zoom(kmask, sizefactor)  # scale back to normal size
    kmask = normalize(kmask)
    kmask = (kmask > mahotas.otsu(kmask.astype(np.uint8)))  # remove artifacts of interpolation

    tifffile.imsave(output_file, img_as_ubyte(kmask), compress=5)


def quantify_tissue_2d(input_dir, output_file, slice_names, voxel_xy, voxel_z):
    pixels = 0
    for file in [input_dir + "/" + x for x in slice_names]:
        mask = io.imread(file)
        pixels += np.count_nonzero(mask)

    volume = pixels * voxel_xy * voxel_xy * voxel_z
    with open(output_file, "w") as f:
        json.dump({
            "num-pixels": pixels,
            "volume-microns3": volume
        }, f, indent=4)


def segment_glomeruli2d(input_file, tissue_mask_file, output_file, voxel_xy):
    kmask = io.imread(tissue_mask_file)
    if kmask.max() == 0:
        tifffile.imsave(output_file, kmask, compress=5)
        return

    # normalize image
    img = io.imread(input_file)
    img = ndimage.median_filter(img, 3)
    img = img * 255. / img.max()

    # remove all intensity variations larger than maximum radius of a glomerulus
    d = mahotas.disk(int(float(glomeruli_maxrad) / voxel_xy))
    img = img - mahotas.open(img.astype(np.uint8), d)
    img = img * 255. / img.max()
    ch = img[np.where(kmask > 0)]

    # segment glomeruli by otsu thresholding	only if this threshold is higher than the 75-th percentile in the kidney mask
    t = mahotas.otsu(img.astype(np.uint8))

    cells = None

    if t > np.percentile(ch, 75) * 1.5:
        cells = img > t
        cells[np.where(kmask == 0)] = 0
        cells = mahotas.open(cells, mahotas.disk(int(float(glomeruli_minrad) / 2. / voxel_xy)))
    else:
        cells = np.zeros_like(img)

    tifffile.imsave(output_file, img_as_ubyte(cells), compress=5)


def segment_glomeruli3d(input_dir, output_dir, slice_names):
    """
    Original implementation from Anna's script
    :param input_dir:
    :param output_dir:
    :param slice_names:
    :param voxel_xy:
    :param voxel_z:
    :return:
    """

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    num = 0
    mask = io.imread(input_dir + "/" + slice_names[0])
    l0 = np.zeros_like(mask)

    labels = []
    limsize = int(float(glomeruli_maxrad))
    nfiles = [output_dir + "/" + x for x in slice_names]

    # label
    for i in range(len(slice_names)):
        mask = io.imread(input_dir + "/" + slice_names[i])
        l, n = ndimage.label(mask)

        labels.append(np.zeros_like(l))
        for j in range(n):  # FOR EACH label
            ind = np.where(l == j + 1)  # Indices Of the current label
            ls = np.unique(l0[ind])
            ls = ls[np.where(ls > 0)]  # Get the connections current_label -> last_layer_label
            if len(ls) == 0:
                num += 1
                labels[-1][ind] = num

            if len(ls) == 1:
                labels[-1][ind] = ls[0]

            if len(ls) > 1:
                labels[-1][ind] = ls[0]  # Assign to target (first encountered)
                for k in range(1, len(ls)):  # FOREACH all other connections
                    for s in range(len(labels)):  # Go through all layers and remove them
                        labels[s] = np.where(labels[s] == ls[k], ls[0], labels[s])
        l0 = labels[-1]

        # if number of layers exceeds limit, save the first layer
        if len(labels) > limsize:
            mask = labels.pop(0)
            fname = nfiles.pop(0)
            tifffile.imsave(fname, img_as_int(mask), compress=5)

    # save remaining layers
    for i in range(len(labels)):
        mask = labels.pop(0)
        fname = nfiles.pop(0)
        tifffile.imsave(fname, img_as_int(mask), compress=5)


def quantify_and_filter_glomeruli3d(label_dir, output_file, slice_names, voxel_xy, voxel_z):
    glomeruli = defaultdict(lambda: { "pixels": 0, "volume": 0, "diameter": 0, "label": 0, "valid": True })

    for file in [label_dir + "/" + x for x in slice_names]:
        label = io.imread(file)
        u, counts = np.unique(label, return_counts=True)
        for i in range(len(counts)):
            key = counts[i]
            if key > 0:
                glomeruli[str(key)]["pixels"] = int(glomeruli[str(key)]["pixels"] + counts[i])

    invalid_glomeruli = set()
    glomerulus_min_volume = 4.0 / 3.0 * np.pi * glomeruli_minrad ** 3
    glomerulus_max_volume = 4.0 / 3.0 * np.pi * glomeruli_maxrad ** 3
    diameter_sum = 0
    diameter_sum_sq = 0

    for key in glomeruli:
        glom = glomeruli[key]
        glom["volume"] = float(glom["pixels"] * voxel_xy * voxel_xy * voxel_z)
        glom["diameter"] = float(2.0 * ((3.0 / 4.0 * glom["volume"] / np.pi) ** (1.0 / 3.0)))
        glom["valid"] = glom["volume"] >= glomerulus_min_volume and glom["volume"] <= glomerulus_max_volume
        if glom["valid"]:
            diameter_sum += glom["diameter"]
            diameter_sum_sq += glom["diameter"] ** 2
        else:
            invalid_glomeruli.add(int(key))

    with open(output_file, "w") as f:
        json.dump({
            "data": glomeruli,
            "valid-glomeruli-number": len(glomeruli) - len(invalid_glomeruli),
            "invalid-glomeruli-number": len(invalid_glomeruli),
            "valid-glomeruli-diameter-average": float(diameter_sum / len(glomeruli)),
            "valid-glomeruli-diameter-variance": float((diameter_sum_sq / len(glomeruli)) - (diameter_sum / len(glomeruli)) ** 2)
        }, f, indent=4)

    # Apply filtering to the labeled images to remove invalid glomeruli
    for file in [label_dir + "/" + x for x in slice_names]:
        label = io.imread(file)
        for invalid in invalid_glomeruli:
            label[label == invalid] = 0
        tifffile.imsave(file, img_as_int(label), compress=5)

