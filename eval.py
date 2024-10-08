import pandas as pd
import torch
from sklearn.metrics import confusion_matrix
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

class LicensePlateEvaluator:
    def __init__(self, localization_csv, character_csv, data_loader, iou_threshold=0.5):
        self.localization_data = self.parse_csv(localization_csv, True)
        self.character_data = self.parse_csv(character_csv, False)
        self.data_loader = data_loader
        self.iou_threshold = iou_threshold
        self.y_true = []
        self.y_pred = []

    def bbox_iou(self, box1, box2):
        inter_x1 = max(box1[0], box2[0])
        inter_y1 = max(box1[1], box2[1])
        inter_x2 = min(box1[2], box2[2])
        inter_y2 = min(box1[3], box2[3])
        inter_area = max(inter_x2 - inter_x1, 0) * max(inter_y2 - inter_y1, 0)
        box1_area = (box1[2] - box1[0]) * (box1[3] - box1[1])
        box2_area = (box2[2] - box2[0]) * (box2[3] - box2[1])
        union = box1_area + box2_area - inter_area
        return inter_area / union if union != 0 else 0

    def parse_csv(self, file_path, is_localization):
        data = pd.read_csv(file_path)
        if is_localization:
            data['Image Filename'] = data['Image Filename'].apply(lambda x: eval(x)[0])
            data['Boxes'] = data['Boxes'].apply(eval)
        else:
            data['Boxes'] = data.apply(lambda row: [row['x1'], row['y1'], row['x2'], row['y2']], axis=1)
        return data

    def evaluate_predictions(self):
        tp_plate, fp_plate, fn_plate = 0, 0, 0
        tp_seg, fp_seg, fn_seg = 0, 0, 0
        tp_class, fp_class, fn_class = 0, 0, 0

        tp_seg_only, fp_seg_only, fn_seg_only = 0, 0, 0
        tp_cls_only, fp_cls_only, fn_cls_only = 0, 0, 0
        for images, boxes, labels, img_filenames in self.data_loader:
            for img, box, label, img_filename in zip(images, boxes, labels, img_filenames):
                # Separate bounding boxes and labels for plates and characters
                plate_boxes = []
                char_boxes = []
                char_labels = []

                # Process each bounding box and label, categorizing them
                for b, l in zip(box, label):
                    if l == 0:  # Label 0 is for plates
                        plate_boxes.append(b)
                    else:  # Other labels are for characters
                        char_boxes.append(b)
                        char_labels.append(l - 1)  # Ensure character labels start from 0

                # Evaluate plate localization
                pred_boxes_plate = self.localization_data[self.localization_data['Image Filename'] == img_filename]['Boxes'].tolist()
                matched_plate = self.match_boxes(plate_boxes, pred_boxes_plate)
                tp_plate += matched_plate['tp']
                fp_plate += matched_plate['fp']
                fn_plate += matched_plate['fn']

                # Evaluate character segmentation
                pred_boxes_char = self.character_data[self.character_data['Image Filename'] == img_filename]['Boxes'].tolist()
                matched_char = self.match_boxes(char_boxes, pred_boxes_char)
                tp_seg += matched_char['tp']
                fp_seg += matched_char['fp']
                fn_seg += matched_char['fn']

                # Evaluate character classification
                pred_labels_char = self.character_data[self.character_data['Image Filename'] == img_filename]['Predicted Class']
                matched_class = self.match_classification(char_boxes, char_labels, pred_boxes_char, pred_labels_char)
                tp_class += matched_class['tp']
                fp_class += matched_class['fp']
                fn_class += matched_class['fn']

                if matched_plate['tp'] == 1:
                    tp_seg_only += matched_char['tp']
                    fp_seg_only += matched_char['fp']
                    fn_seg_only += matched_char['fn']
                    self.match_classification_detected_only(char_boxes, char_labels, pred_boxes_char, pred_labels_char)
                
        # Print and return results for all tasks
        results_plate = self.print_evaluation_results(tp_plate, fp_plate, fn_plate, "License Plate Localization")
        results_seg = self.print_evaluation_results(tp_seg, fp_seg, fn_seg, "Character Segmentation")
        results_class = self.print_evaluation_results(tp_class, fp_class, fn_class, "Character Classification")
        
        # Print result for each model individually
        results_seg_model = self.print_evaluation_results(tp_seg_only, fp_seg_only, fn_seg_only, "Character Segmentation Only")

        # Get result for classification from confusion matrix
        tp_cls_only, fp_cls_only, fn_cls_only = self.get_classification_confusion_matrix()
        results_class_model = self.print_evaluation_results(tp_cls_only, fp_cls_only, fn_cls_only, "Character Classification Only")
        
        return {"license_plate": results_plate, "segmentation": results_seg, "classification": results_class, "segmentation_only": results_seg_model, "classification_only": results_class_model}

    def match_boxes(self, gt_boxes, pred_boxes):
        tp, fp, fn = 0, 0, 0
        matched_indices = set()
        for pred_box in pred_boxes:
            best_iou = 0
            best_match_idx = None
            for idx, gt_box in enumerate(gt_boxes):
                iou = self.bbox_iou(pred_box, gt_box)
                if iou > best_iou:
                    best_iou = iou
                    best_match_idx = idx
            if best_iou >= self.iou_threshold:
                if best_match_idx not in matched_indices:
                    tp += 1
                    matched_indices.add(best_match_idx)
                else:
                    fp += 1
            else:
                fp += 1
        fn = len(gt_boxes) - len(matched_indices)
        return {'tp': tp, 'fp': fp, 'fn': fn}

    def match_classification(self, gt_boxes, gt_labels, pred_boxes, pred_labels):
        tp, fp, fn = 0, 0, 0
        matched_indices = set()
        for pred_box, pred_label in zip(pred_boxes, pred_labels):
            best_iou = 0
            best_match_idx = None
            for idx, (gt_box, gt_label) in enumerate(zip(gt_boxes, gt_labels)):
                iou = self.bbox_iou(pred_box, gt_box)
                if iou > best_iou:
                    best_iou = iou
                    best_match_idx = idx
            if best_iou >= self.iou_threshold and best_match_idx not in matched_indices:
                if pred_label == gt_labels[best_match_idx]:
                    tp += 1
                else:
                    fp += 1
                matched_indices.add(best_match_idx)
            else:
                fp += 1
        fn = len(gt_labels) - tp
        return {'tp': tp, 'fp': fp, 'fn': fn}

    def match_classification_detected_only(self, gt_boxes, gt_labels, pred_boxes, pred_labels):
        matched_indices = set()
        for pred_box, pred_label in zip(pred_boxes, pred_labels):
            best_iou = 0
            best_match_idx = None
            for idx, (gt_box, gt_label) in enumerate(zip(gt_boxes, gt_labels)):
                iou = self.bbox_iou(pred_box, gt_box)
                if iou > best_iou:
                    best_iou = iou
                    best_match_idx = idx
            # If detected bounding box matches gt bounding box and not matched before
            if best_iou >= self.iou_threshold and best_match_idx not in matched_indices:
                self.y_true.append(gt_labels[best_match_idx])
                self.y_pred.append(pred_label)
                matched_indices.add(best_match_idx)
        return 0
        

    def print_evaluation_results(self, tp, fp, fn, task_name):
        precision = tp / (tp + fp) if tp + fp > 0 else 0
        recall = tp / (tp + fn) if tp + fn > 0 else 0
        f1_score = 2 * (precision * recall) / (precision + recall) if precision + recall > 0 else 0
        print(f"{task_name} - Precision: {precision:.2f}, Recall: {recall:.2f}, F1 Score: {f1_score:.2f}")
        return {"precision": precision, "recall": recall, "f1_score": f1_score}

    def get_classification_confusion_matrix(self):
        # Get confusion matrix
        cm = confusion_matrix(self.y_true, self.y_pred)
        # Initialize arrays to hold TP, FP, FN
        tp_cls_only = np.diag(cm)
        fp_cls_only = np.sum(cm, axis=0) - tp_cls_only
        fn_cls_only = np.sum(cm, axis=1) - tp_cls_only
        
        total_FP = np.sum(fp_cls_only)
        total_FN = np.sum(fn_cls_only)
        total_TP = np.sum(tp_cls_only)
        
        return total_TP, total_FP, total_FN

# Example usage
# evaluator = LicensePlateEvaluator('localization.csv', 'character.csv', data_loader, iou_threshold=0.5)
# results = evaluator.evaluate_predictions()
# print(results)
