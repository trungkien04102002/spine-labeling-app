"""
Data Augmentation for 3D Medical Imaging (SpineNetV2).

Implements medically appropriate augmentations for lumbar spine MRI:
- Geometric transforms (flip, rotation)
- Intensity transforms (brightness, contrast, noise)
- Class-aware oversampling for minority classes

All transforms share the API ``(volume, labels=None) -> (volume, labels)``.
Horizontal flipping swaps any ``left_*``/``right_*`` paired labels in-place;
other transforms pass the labels dict through unchanged.

Author: SpineNetV2 Improved Implementation
"""

import torch
import numpy as np
import random


def _swap_lr_labels(labels):
    """Swap any left_<X>/right_<X> paired entries in labels.

    Labels dict is shallow-copied; original is left untouched. Keys without a
    matching ``right_<X>`` counterpart pass through. Values can be ints, -1
    sentinel for missing, or torch tensors — only references are swapped.
    """
    if labels is None:
        return labels
    swapped = dict(labels)
    for key in list(labels.keys()):
        if key.startswith("left_"):
            mate = "right_" + key[len("left_"):]
            if mate in labels:
                swapped[key], swapped[mate] = labels[mate], labels[key]
    return swapped


class RandomHorizontalFlip:
    """
    Randomly flip the volume horizontally (left-right) AND swap left/right
    paired labels (e.g. left_foraminal <-> right_foraminal).

    Without label swapping, half of the foraminal training samples would be
    label-noisy because the flipped image's left foramen is on the right side
    while the label says "left". This class is the corrected version.

    The constructor accepts ``swap_labels=False`` for v2 reproducibility:
    that legacy mode does NOT swap labels on flip, reproducing the original
    label-noise behavior. The noise (~25 % of foraminal samples flipped
    without label swap, given p=0.5) acts as accidental regularization that
    helped v2 break the Severe-foraminal F1=0 threshold. v3 with
    ``swap_labels=True`` (default) is mathematically correct but loses that
    free regularization, so foraminal-Severe may need stronger oversampling
    or a smaller focal_gamma to break threshold.
    """
    def __init__(self, p=0.5, swap_labels=True):
        """
        Args:
            p: Probability of applying the flip (default: 0.5)
            swap_labels: If True (default), swap left_*/right_* paired labels
                on flip. Set False to reproduce the v2 buggy behavior — useful
                only for ablation/reproducibility experiments.
        """
        self.p = p
        self.swap_labels = swap_labels

    def __call__(self, volume, labels=None):
        """
        Args:
            volume: Tensor of shape (9, 112, 224) or (C, D, H, W)
            labels: Optional dict; left_*/right_* pairs are swapped on flip
                when ``swap_labels=True`` (default).
        Returns:
            (flipped_volume, maybe_swapped_labels) tuple
        """
        if random.random() < self.p:
            volume = torch.flip(volume, dims=[-1])
            if self.swap_labels:
                labels = _swap_lr_labels(labels)
        return volume, labels


class RandomRotation:
    """
    Randomly rotate the volume by a small angle.

    Medical justification: Patient positioning varies slightly.
    Small rotations (±10°) preserve anatomical features.
    """
    def __init__(self, degrees=10):
        """
        Args:
            degrees: Maximum rotation angle in degrees (default: 10)
        """
        self.degrees = degrees

    def __call__(self, volume, labels=None):
        """
        Args:
            volume: Tensor of shape (9, 112, 224) or (C, D, H, W)
            labels: Optional dict; passed through unchanged (rotation does
                not flip L/R semantics, just rotates within plane).
        Returns:
            (rotated_volume, labels) tuple
        """
        # Random angle in range [-degrees, +degrees]
        angle = random.uniform(-self.degrees, self.degrees)

        # Convert to numpy for rotation
        volume_np = volume.numpy() if isinstance(volume, torch.Tensor) else volume

        # Rotate each slice in the depth dimension
        rotated_slices = []
        for i in range(volume_np.shape[0]):
            slice_2d = volume_np[i]
            # Create rotation matrix
            h, w = slice_2d.shape
            center = (w // 2, h // 2)
            M = self._get_rotation_matrix(center, angle, scale=1.0)
            # Apply rotation
            rotated = self._warp_affine(slice_2d, M, (w, h))
            rotated_slices.append(rotated)

        rotated_volume = np.stack(rotated_slices, axis=0)

        return torch.from_numpy(rotated_volume).float(), labels

    @staticmethod
    def _get_rotation_matrix(center, angle, scale):
        """Compute 2D rotation matrix."""
        angle_rad = np.deg2rad(angle)
        cos_val = np.cos(angle_rad)
        sin_val = np.sin(angle_rad)

        cx, cy = center
        M = np.array([
            [scale * cos_val, scale * sin_val, (1 - scale * cos_val) * cx - scale * sin_val * cy],
            [-scale * sin_val, scale * cos_val, scale * sin_val * cx + (1 - scale * cos_val) * cy]
        ], dtype=np.float32)
        return M

    @staticmethod
    def _warp_affine(image, M, output_shape):
        """Simple affine transformation (rotation)."""
        from scipy import ndimage
        # Use scipy for rotation
        h, w = image.shape
        cy, cx = h // 2, w // 2
        angle = np.arctan2(M[1, 0], M[0, 0]) * 180 / np.pi
        rotated = ndimage.rotate(image, -angle, reshape=False, order=1, mode='nearest')
        return rotated


class RandomBrightnessContrast:
    """
    Randomly adjust brightness and contrast.

    Medical justification: MRI intensity varies across scanners and protocols.
    Augmentation improves generalization.
    """
    def __init__(self, brightness_limit=0.2, contrast_limit=0.2, p=0.5):
        """
        Args:
            brightness_limit: Range for brightness adjustment [-limit, +limit]
            contrast_limit: Range for contrast adjustment [-limit, +limit]
            p: Probability of applying the transform
        """
        self.brightness_limit = brightness_limit
        self.contrast_limit = contrast_limit
        self.p = p

    def __call__(self, volume, labels=None):
        """
        Args:
            volume: Tensor of shape (9, 112, 224)
            labels: Optional dict; passed through unchanged.
        Returns:
            (adjusted_volume, labels) tuple
        """
        if random.random() < self.p:
            brightness = random.uniform(-self.brightness_limit, self.brightness_limit)
            contrast = random.uniform(-self.contrast_limit, self.contrast_limit)
            contrast_factor = 1.0 + contrast

            volume = volume * contrast_factor + brightness
            volume = torch.clamp(volume, 0.0, 1.0)

        return volume, labels


class RandomGaussianNoise:
    """
    Add random Gaussian noise to the volume.

    Medical justification: Simulates scanner noise and artifacts.
    Improves model robustness.
    """
    def __init__(self, std_limit=0.05, p=0.3):
        """
        Args:
            std_limit: Maximum standard deviation of noise
            p: Probability of applying noise
        """
        self.std_limit = std_limit
        self.p = p

    def __call__(self, volume, labels=None):
        """
        Args:
            volume: Tensor of shape (9, 112, 224)
            labels: Optional dict; passed through unchanged.
        Returns:
            (noisy_volume, labels) tuple
        """
        if random.random() < self.p:
            std = random.uniform(0, self.std_limit)
            noise = torch.randn_like(volume) * std
            volume = volume + noise
            volume = torch.clamp(volume, 0.0, 1.0)

        return volume, labels


class Compose:
    """
    Compose multiple transforms.

    Example:
        >>> transform = Compose([
        >>>     RandomHorizontalFlip(p=0.5),
        >>>     RandomRotation(degrees=10),
        >>>     RandomBrightnessContrast(p=0.5),
        >>> ])
        >>> augmented = transform(volume)
    """
    def __init__(self, transforms):
        """
        Args:
            transforms: List of transform objects
        """
        self.transforms = transforms

    def __call__(self, volume, labels=None):
        """
        Apply all transforms sequentially.

        Args:
            volume: Input tensor
            labels: Optional dict; threaded through every transform.
        Returns:
            (volume, labels) tuple
        """
        for t in self.transforms:
            volume, labels = t(volume, labels)
        return volume, labels


def get_training_augmentation(mode='medium', hflip_swap_labels=True):
    """
    Get predefined augmentation pipeline for training.

    Args:
        mode: 'light', 'medium', or 'heavy'
        hflip_swap_labels: If True (default), HFlip swaps left_*/right_*
            labels (correct behavior). If False, reproduces v2 buggy
            label-noise behavior — useful only for ablation/reproducibility.

    Returns:
        Compose object with augmentation transforms
    """
    if mode == 'light':
        return Compose([
            RandomHorizontalFlip(p=0.5, swap_labels=hflip_swap_labels),
            RandomBrightnessContrast(brightness_limit=0.1, contrast_limit=0.1, p=0.3),
        ])
    elif mode == 'medium':
        return Compose([
            RandomHorizontalFlip(p=0.5, swap_labels=hflip_swap_labels),
            RandomRotation(degrees=10),
            RandomBrightnessContrast(brightness_limit=0.2, contrast_limit=0.2, p=0.5),
            RandomGaussianNoise(std_limit=0.05, p=0.3),
        ])
    elif mode == 'heavy':
        return Compose([
            RandomHorizontalFlip(p=0.5, swap_labels=hflip_swap_labels),
            RandomRotation(degrees=15),
            RandomBrightnessContrast(brightness_limit=0.3, contrast_limit=0.3, p=0.7),
            RandomGaussianNoise(std_limit=0.08, p=0.5),
        ])
    else:
        raise ValueError(f"Unknown mode: {mode}. Choose 'light', 'medium', or 'heavy'.")


def _resolve_get_labels(dataset):
    """Return a callable get_labels(idx) -> labels dict for `dataset`,
    or None if no fast label-only path exists.

    Walks Subset wrappers so we hit the underlying dataset's get_labels()
    instead of triggering a full __getitem__ (which loads .npy volumes).
    """
    if hasattr(dataset, 'get_labels'):
        return dataset.get_labels

    if isinstance(dataset, torch.utils.data.Subset):
        inner_get_labels = _resolve_get_labels(dataset.dataset)
        if inner_get_labels is not None:
            mapping = dataset.indices
            return lambda i: inner_get_labels(mapping[i])

    return None


class OversamplingDataset(torch.utils.data.Dataset):
    """
    Dataset wrapper that oversamples minority classes.

    For RSNA, oversamples Moderate and Severe cases to balance classes.
    """
    def __init__(self, base_dataset, oversample_factor=5, target_classes=[1, 2]):
        """
        Args:
            base_dataset: Base dataset to wrap
            oversample_factor: How many times to repeat minority samples
            target_classes: Which classes to oversample (default: [1, 2] = Moderate, Severe)
        """
        self.base_dataset = base_dataset
        self.oversample_factor = oversample_factor
        self.target_classes = target_classes

        # Build augmented index list
        self.indices = self._build_indices()

    def _build_indices(self):
        """Build list of indices with oversampling.

        Uses _resolve_get_labels() to find a fast label-only path through
        Subset/wrapper layers, avoiding 7800 full-volume disk reads.
        """
        n = len(self.base_dataset)
        indices = list(range(n))

        get_labels = _resolve_get_labels(self.base_dataset)

        for i in range(n):
            if get_labels is not None:
                labels = get_labels(i)
            else:
                _, labels = self.base_dataset[i]

            has_minority = any(
                labels[c] in self.target_classes
                for c in ('spinal_canal', 'left_foraminal', 'right_foraminal')
            )

            if has_minority:
                indices.extend([i] * (self.oversample_factor - 1))

        return indices

    def __len__(self):
        return len(self.indices)

    def __getitem__(self, idx):
        """Get item from base dataset using oversampled indices."""
        base_idx = self.indices[idx]
        return self.base_dataset[base_idx]


# Example usage
if __name__ == "__main__":
    print("Testing augmentation module...")

    # Create dummy volume
    volume = torch.rand(9, 112, 224)

    labels = {"spinal_canal": 0, "left_foraminal": 1, "right_foraminal": 2}

    print("\n1. Testing RandomHorizontalFlip with labels...")
    flip = RandomHorizontalFlip(p=1.0)
    flipped, swapped = flip(volume, dict(labels))
    print(f"   Original: {volume.shape}, Flipped: {flipped.shape}")
    print(f"   Labels in : {labels}")
    print(f"   Labels out: {swapped}  (left/right_foraminal must be swapped)")
    assert swapped["left_foraminal"] == labels["right_foraminal"], "L/R swap failed"
    assert swapped["right_foraminal"] == labels["left_foraminal"], "L/R swap failed"
    assert swapped["spinal_canal"] == labels["spinal_canal"], "spinal_canal must not change"

    print("\n2. Testing RandomRotation...")
    rotate = RandomRotation(degrees=10)
    rotated, lbl_out = rotate(volume, dict(labels))
    print(f"   Original: {volume.shape}, Rotated: {rotated.shape}")
    assert lbl_out == labels, "Rotation must not change labels"

    print("\n3. Testing RandomBrightnessContrast...")
    bright = RandomBrightnessContrast(p=1.0)
    adjusted, _ = bright(volume, dict(labels))
    print(f"   Original range: [{volume.min():.3f}, {volume.max():.3f}]")
    print(f"   Adjusted range: [{adjusted.min():.3f}, {adjusted.max():.3f}]")

    print("\n4. Testing RandomGaussianNoise...")
    noise = RandomGaussianNoise(p=1.0)
    noisy, _ = noise(volume, dict(labels))
    print(f"   Original: {volume.shape}, Noisy: {noisy.shape}")

    print("\n5. Testing Compose...")
    transform = get_training_augmentation(mode='medium')
    augmented, lbl_after = transform(volume, dict(labels))
    print(f"   Original: {volume.shape}, Augmented: {augmented.shape}")
    print(f"   Labels after compose: {lbl_after}")

    print("\n✓ All transforms working!")
