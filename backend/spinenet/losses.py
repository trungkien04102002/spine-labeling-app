"""
Loss Functions for SpineNetV2.

Implements:
1. FocalLoss: Handles class imbalance by focusing on hard examples
2. UncertaintyLoss: Multi-task learning with learnable task weights

Author: SpineNetV2 Improved Implementation
"""

import torch
import torch.nn as nn
import torch.nn.functional as F


class FocalLoss(nn.Module):
    """
    Focal Loss for addressing class imbalance.

    Reference:
        Lin et al. "Focal Loss for Dense Object Detection" ICCV 2017
        https://arxiv.org/abs/1708.02002

    Formula:
        FL(p_t) = -alpha_t * (1 - p_t)^gamma * log(p_t)

    Where:
        - p_t: probability of correct class
        - alpha_t: class weight (balances class frequencies)
        - gamma: focusing parameter (down-weights easy examples)

    Intuition:
        - Easy examples (p_t → 1): (1-p_t)^gamma → 0, loss → 0
        - Hard examples (p_t → 0): (1-p_t)^gamma → 1, loss is large
        - Gamma=0: equivalent to CrossEntropyLoss
        - Gamma=2: recommended default
    """
    def __init__(self, alpha=None, gamma=2.0, reduction='mean', ignore_index=-1):
        """
        Args:
            alpha: Class weights tensor [num_classes] or None for uniform weights
            gamma: Focusing parameter (default: 2.0)
            reduction: 'mean', 'sum', or 'none'
            ignore_index: Class index to ignore (e.g., -1 for missing labels)
        """
        super(FocalLoss, self).__init__()
        self.alpha = alpha
        self.gamma = gamma
        self.reduction = reduction
        self.ignore_index = ignore_index

    def forward(self, inputs, targets):
        """
        Args:
            inputs: Logits [B, num_classes]
            targets: Ground truth labels [B]
        Returns:
            Focal loss value
        """
        # Get probabilities
        ce_loss = F.cross_entropy(inputs, targets, reduction='none', ignore_index=self.ignore_index)
        p = torch.exp(-ce_loss)  # p_t: probability of correct class

        # Focal term: (1 - p_t)^gamma
        focal_term = (1 - p) ** self.gamma

        # Apply class weights if provided
        if self.alpha is not None:
            if self.alpha.device != inputs.device:
                self.alpha = self.alpha.to(inputs.device)
            # Get alpha for each target
            alpha_t = self.alpha.gather(0, targets.clamp(min=0))  # Clamp to avoid -1 indexing
            # Set alpha=0 for ignore_index
            alpha_t = torch.where(targets == self.ignore_index, torch.zeros_like(alpha_t), alpha_t)
            focal_term = alpha_t * focal_term

        # Focal loss
        loss = focal_term * ce_loss

        # Reduction
        if self.reduction == 'mean':
            # Only average over non-ignored samples
            valid_mask = (targets != self.ignore_index)
            if valid_mask.sum() > 0:
                return loss.sum() / valid_mask.sum()
            else:
                return loss.sum() * 0.0  # Return 0 if all samples ignored
        elif self.reduction == 'sum':
            return loss.sum()
        else:
            return loss


class UncertaintyLoss(nn.Module):
    """
    Multi-Task Learning with Uncertainty Weighting.

    Reference:
        Kendall et al. "Multi-Task Learning Using Uncertainty to Weigh Losses for Scene Geometry and Semantics" CVPR 2018
        https://arxiv.org/abs/1705.07115

    Learns optimal task weights automatically using homoscedastic uncertainty.

    Formula:
        L_total = sum_i [ (1 / (2*sigma_i^2)) * L_i + log(sigma_i) ]

    Where:
        - L_i: loss for task i
        - sigma_i: learned uncertainty (log variance) for task i
        - First term: scales loss by inverse uncertainty
        - Second term: regularization to prevent sigma → infinity

    Intuition:
        - High uncertainty (large sigma): task is harder, reduce its weight
        - Low uncertainty (small sigma): task is easier, increase its weight
        - Automatically balances tasks during training
    """
    def __init__(self, num_tasks=3):
        """
        Args:
            num_tasks: Number of tasks (default: 3 for RSNA dataset)
        """
        super(UncertaintyLoss, self).__init__()

        # Learnable log variance for each task (log(sigma^2))
        # Initialized to 0 → sigma^2 = 1 → equal weights initially
        self.log_vars = nn.Parameter(torch.zeros(num_tasks))

    def forward(self, losses):
        """
        Args:
            losses: List or tensor of per-task losses [L_1, L_2, L_3]
        Returns:
            Weighted total loss
        """
        if isinstance(losses, list):
            losses = torch.stack(losses)

        # Compute weighted loss
        # L = sum_i [ exp(-log_var_i) * loss_i + log_var_i ]
        #   = sum_i [ (1 / sigma_i^2) * loss_i + log(sigma_i^2) ]
        precision = torch.exp(-self.log_vars)  # 1 / sigma^2
        weighted_losses = precision * losses + self.log_vars

        return weighted_losses.sum(), precision

    def get_task_weights(self):
        """
        Get current task weights (1 / sigma^2).

        Returns:
            Tensor of task weights [num_tasks]
        """
        return torch.exp(-self.log_vars)

    def get_uncertainties(self):
        """
        Get current task uncertainties (sigma^2).

        Returns:
            Tensor of task uncertainties [num_tasks]
        """
        return torch.exp(self.log_vars)


def compute_class_weights(dataset, num_classes=3, mode='inverse'):
    """
    Compute class weights for imbalanced datasets.

    Args:
        dataset: Dataset object with labels
        num_classes: Number of classes (default: 3 for RSNA)
        mode: 'inverse' or 'effective' or 'sqrt'

    Returns:
        Class weights tensor [num_classes]
    """
    # Count samples per class. Use _resolve_get_labels to find a fast
    # label-only path (handling Subset wrappers).
    from spinenet.augmentation import _resolve_get_labels

    class_counts = torch.zeros(num_classes)
    get_labels = _resolve_get_labels(dataset)

    for idx in range(len(dataset)):
        if get_labels is not None:
            labels = get_labels(idx)
        else:
            _, labels = dataset[idx]
        for condition in ['spinal_canal', 'left_foraminal', 'right_foraminal']:
            label = labels[condition]
            if hasattr(label, 'item'):
                label = label.item()
            if label != -1:
                class_counts[label] += 1

    # Compute weights
    if mode == 'inverse':
        # weight = 1 / count
        weights = 1.0 / class_counts
    elif mode == 'effective':
        # Effective number of samples: (1 - beta^n) / (1 - beta)
        # Beta=0.9999 recommended for medical imaging
        beta = 0.9999
        effective_num = 1.0 - torch.pow(beta, class_counts)
        weights = (1.0 - beta) / effective_num
    elif mode == 'sqrt':
        # weight = 1 / sqrt(count)
        weights = 1.0 / torch.sqrt(class_counts)
    else:
        raise ValueError(f"Unknown mode: {mode}")

    # Normalize weights to sum to num_classes
    weights = weights / weights.sum() * num_classes

    return weights
