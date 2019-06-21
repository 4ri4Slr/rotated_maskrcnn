# Mask Scoring R-CNN
# Written by zhaojin.huang, 2018-12.
# Adapted by vincent.looi, 2019-06.

# import numpy as np
import torch
from torch import nn
# import torch.nn.functional as F

from maskrcnn_benchmark.structures.boxlist_ops import cat_boxlist

# TODO get the predicted maskiou and mask score.
class MaskIoUPostProcessor(nn.Module):
    """
    Getting the maskiou according to the targeted label, and computing the mask score according to maskiou.
    """

    def __init__(self, cfg):
        super(MaskIoUPostProcessor, self).__init__()

        self.use_nms = cfg.MODEL.ROI_MASKIOU_HEAD.USE_NMS
        if self.use_nms:
            self.rotated = cfg.MODEL.ROTATED
            self.detections_per_img = cfg.MODEL.ROI_HEADS.DETECTIONS_PER_IMG
            self.score_thresh = cfg.MODEL.ROI_HEADS.SCORE_THRESH
            self.nms_thresh = cfg.MODEL.ROI_HEADS.NMS

            if self.rotated:
                from maskrcnn_benchmark.modeling.rotate_ops import RotateNMS
                self.nms = RotateNMS(nms_threshold=self.nms_thresh)
            else:
                from maskrcnn_benchmark.layers import nms as _box_nms
                self.nms = _box_nms

    def forward(self, boxes, pred_maskiou, labels):
        ix = 0
        for box, pm_iou, label in zip(boxes, pred_maskiou, labels):
            num_masks = pm_iou.shape[0]
            index = torch.arange(num_masks, device=label.device)
            maskious = pm_iou[index, label]

            bbox_scores = box.get_field("scores")
            mask_scores = bbox_scores * maskious
            box.add_field("mask_scores", mask_scores)

            if self.use_nms:
                num_classes = pm_iou.shape[1]
                boxlist = self.filter_results(box, num_classes)
                boxes[ix] = boxlist

            ix += 1

        return boxes

    def filter_results(self, boxlist, num_classes):
        """Returns bounding-box detection results by thresholding on scores and
        applying non-maximum suppression (NMS).
        """
        if self.rotated:
            boxes = boxlist.get_field("rrects")  # (N,5)
        else:
            boxes = boxlist.bbox  # (N,4)
        mask_scores = boxlist.get_field("mask_scores")  # (N)
        labels = boxlist.get_field("labels")  # (N)

        # device = mask_scores.device
        result = []
        # Apply threshold on detection probabilities and apply NMS
        inds_all = mask_scores > self.score_thresh
        for j in range(1, num_classes):
            inds = (labels == j) * inds_all
            inds = inds.nonzero().squeeze(1)
            boxes_j = boxes[inds]
            scores_j = mask_scores[inds]

            # perform nms
            if self.rotated:
                # sort scores!
                sorted_idx = torch.sort(scores_j, descending=True)[1]
                boxes_j = boxes_j[sorted_idx]
                inds = inds[sorted_idx]

                keep = self.nms(boxes_j)
            else:
                keep = self.nms(boxes_j, scores_j, self.nms_thresh)

            boxlist_for_class = boxlist[inds][keep]

            result.append(boxlist_for_class)

        result = cat_boxlist(result)
        number_of_detections = len(result)

        # Limit to max_per_image detections **over all classes**
        if number_of_detections > self.detections_per_img > 0:
            cls_scores = result.get_field("scores")
            image_thresh, _ = torch.kthvalue(
                cls_scores.cpu(), number_of_detections - self.detections_per_img + 1
            )
            keep = cls_scores >= image_thresh.item()
            keep = torch.nonzero(keep).squeeze(1)
            result = result[keep]
        return result

def make_roi_maskiou_post_processor(cfg):
    maskiou_post_processor = MaskIoUPostProcessor(cfg)
    return maskiou_post_processor
