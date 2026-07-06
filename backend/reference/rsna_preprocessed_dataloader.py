"""
Fast RSNA DataLoader for Preprocessed .npy Files

Loads preprocessed IVD volumes from .npy files (much faster than DICOM).

Usage:
    from rsna_preprocessed_dataloader import RSNAPreprocessedDataset

    dataset = RSNAPreprocessedDataset(
        data_dir='rsna_preprocessed',
        split='train'
    )

    # Use in training
    from torch.utils.data import DataLoader
    loader = DataLoader(dataset, batch_size=16, shuffle=True)
"""

import numpy as np
import pandas as pd
import torch
from torch.utils.data import Dataset
from pathlib import Path
from typing import Dict, Tuple


class RSNAPreprocessedDataset(Dataset):
    """
    Fast PyTorch Dataset for preprocessed RSNA volumes (.npy files).

    Much faster than loading from DICOM during training.
    """

    def __init__(
        self,
        data_dir: str,
        split: str = 'train',
        transform=None
    ):
        """
        Args:
            data_dir: Path to preprocessed data directory (rsna_preprocessed)
            split: 'train' or 'test'
            transform: Optional transform to apply
        """
        self.data_dir = Path(data_dir)
        self.split = split
        self.transform = transform

        # Load metadata
        metadata_path = self.data_dir / f'{split}_metadata.csv'
        if not metadata_path.exists():
            raise FileNotFoundError(
                f"Metadata not found: {metadata_path}\n"
                f"Run prepare_rsna_data.py first to preprocess the dataset."
            )

        self.metadata = pd.read_csv(metadata_path)
        self.volumes_dir = self.data_dir / 'volumes'

        print(f"✓ Loaded {len(self.metadata)} preprocessed samples from {data_dir}")

    def __len__(self) -> int:
        return len(self.metadata)

    def get_labels(self, idx: int) -> Dict[str, int]:
        row = self.metadata.iloc[idx]
        return {
            'spinal_canal': int(row['spinal_canal']),
            'left_foraminal': int(row['left_foraminal']),
            'right_foraminal': int(row['right_foraminal']),
        }

    def __getitem__(self, idx: int) -> Tuple[torch.Tensor, Dict[str, int]]:
        """
        Get one preprocessed IVD sample.

        Returns:
            volume: torch.Tensor of shape (9, 112, 224)
            labels: dict with keys 'spinal_canal', 'left_foraminal', 'right_foraminal'
        """
        # Get metadata
        row = self.metadata.iloc[idx]

        # Load preprocessed volume from .npy file
        # Support both new structure (filepath: study_id/series_level.npy)
        # and old structure (filename: study_series_level.npy)
        if 'filepath' in row:
            volume_path = self.volumes_dir / row['filepath']
        else:  # Backward compatibility
            volume_path = self.volumes_dir / row['filename']

        volume = np.load(volume_path)

        # Convert to tensor
        volume = torch.from_numpy(volume).float()

        # Build labels first so the transform can swap left/right pairs on flip.
        labels = {
            'spinal_canal': int(row['spinal_canal']),
            'left_foraminal': int(row['left_foraminal']),
            'right_foraminal': int(row['right_foraminal'])
        }

        if self.transform is not None:
            volume, labels = self.transform(volume, labels)

        return volume, labels


# Example usage
if __name__ == "__main__":
    print("="*70)
    print("RSNA Preprocessed Dataset - Quick Test")
    print("="*70)

    # Check if preprocessed data exists
    data_dir = 'rsna_preprocessed'
    if not Path(data_dir).exists():
        print(f"\n❌ Preprocessed data not found: {data_dir}")
        print("\nRun preprocessing first:")
        print("  python3 prepare_rsna_data.py")
        exit(1)

    # Create dataset
    print(f"\nLoading dataset from {data_dir}...")
    dataset = RSNAPreprocessedDataset(data_dir=data_dir, split='train')

    # Test loading one sample
    print("\nTesting sample loading...")
    volume, labels = dataset[0]

    print(f"\n✓ Sample loaded successfully!")
    print(f"  - Volume shape: {volume.shape}")
    print(f"  - Volume dtype: {volume.dtype}")
    print(f"  - Volume range: [{volume.min():.3f}, {volume.max():.3f}]")
    print(f"  - Labels: {labels}")

    # Test with DataLoader
    print("\nTesting DataLoader (batching)...")
    from torch.utils.data import DataLoader

    loader = DataLoader(dataset, batch_size=4, shuffle=True, num_workers=2)
    batch_volumes, batch_labels = next(iter(loader))

    print(f"✓ Batch loaded!")
    print(f"  - Batch shape: {batch_volumes.shape}")
    print(f"  - Batch labels: {batch_labels}")

    # Test with model
    print("\nTesting with grading model...")
    from spinenet.models.grading_baseline import GradingModelBaseline

    model = GradingModelBaseline(format='rsna')
    model.eval()

    # Add channel dimension
    batch_input = batch_volumes.unsqueeze(1)  # [4, 1, 9, 112, 224]

    with torch.no_grad():
        outputs = model(batch_input)

    print(f"✓ Model inference successful!")
    print(f"  - Output keys: {list(outputs.keys())}")
    for key, value in outputs.items():
        print(f"  - {key}: {value.shape}")

    print("\n" + "="*70)
    print("✓ ALL TESTS PASSED!")
    print("="*70)
    print("\nPreprocessed dataset is ready for training!")
    print(f"  - {len(dataset)} samples")
    print(f"  - Fast loading from .npy files")
    print(f"  - Compatible with grading model")
    print()
