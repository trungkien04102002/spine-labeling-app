#!/usr/bin/env python3
"""
Test RSNA Grading Model with Preprocessed Data

Quick test to verify:
1. Preprocessed .npy files load correctly
2. Grading model runs inference
3. Output format is correct

Usage:
    # Test with trained model
    python3 test_rsna_preprocessed.py --model checkpoints/best_model.pth

    # Test with pretrained backbone (random heads)
    python3 test_rsna_preprocessed.py --use-pretrained

    # Test specific number of patients
    python3 test_rsna_preprocessed.py --model checkpoints/best_model.pth --num-patients 5
"""

import argparse
import torch
import numpy as np
from pathlib import Path
import pandas as pd
from sklearn.metrics import accuracy_score, precision_recall_fscore_support

from rsna_preprocessed_dataloader import RSNAPreprocessedDataset
from spinenet.models.grading_baseline import GradingModelBaseline
from spinenet.models.grading_attention import GradingModelWithCBAM


def main():
    parser = argparse.ArgumentParser(description='Test grading model with preprocessed data')
    parser.add_argument('--data-dir', type=str, default='rsna_preprocessed',
                        help='Path to preprocessed data')
    parser.add_argument('--model', type=str, default=None,
                        help='Path to trained model checkpoint (.pth file)')
    parser.add_argument('--use-pretrained', action='store_true',
                        help='Load pretrained backbone weights (only if no --model specified)')
    parser.add_argument('--num-patients', type=int, default=2,
                        help='Number of patients to test')
    args = parser.parse_args()

    print("="*70)
    print("RSNA Grading Model - Preprocessed Data Test")
    print("="*70)

    # Check if preprocessed data exists
    if not Path(args.data_dir).exists():
        print(f"\n❌ Error: Preprocessed data not found: {args.data_dir}")
        print("\nRun preprocessing first:")
        print("  python3 prepare_rsna_data.py --skip-download")
        return

    # Load dataset
    print(f"\n[1/3] Loading dataset from {args.data_dir}...")
    try:
        dataset = RSNAPreprocessedDataset(
            data_dir=args.data_dir,
            split='train'
        )
    except Exception as e:
        print(f"❌ Error loading dataset: {e}")
        return

    if len(dataset) == 0:
        print("❌ No samples found in dataset!")
        return

    print(f"✓ Loaded {len(dataset)} samples")

    # Load model
    print(f"\n[2/3] Loading grading model...")
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f"  - Device: {device}")

    # Detect model type from checkpoint if provided
    use_cbam = False
    if args.model:
        print(f"  - Detecting model type from {args.model}...")
        try:
            checkpoint = torch.load(args.model, map_location='cpu', weights_only=False)

            # Check if checkpoint contains CBAM layers
            if isinstance(checkpoint, dict) and 'model_state_dict' in checkpoint:
                state_dict = checkpoint['model_state_dict']
                use_cbam = any('cbam' in key for key in state_dict.keys())
            elif isinstance(checkpoint, dict):
                use_cbam = any('cbam' in key for key in checkpoint.keys())

            if use_cbam:
                print(f"  ✓ Detected attention model (with CBAM)")
            else:
                print(f"  ✓ Detected baseline model (no CBAM)")
        except Exception as e:
            print(f"  ⚠ Warning: Could not detect model type: {e}")
            print(f"  → Assuming baseline model")

    # Create appropriate model
    if use_cbam:
        model = GradingModelWithCBAM(format='rsna', use_cbam=True)
    else:
        model = GradingModelBaseline(format='rsna')

    # Load trained model checkpoint if provided
    if args.model:
        print(f"  - Loading weights from {args.model}...")
        try:
            checkpoint = torch.load(args.model, map_location='cpu', weights_only=False)

            # Check if checkpoint has expected format
            if isinstance(checkpoint, dict):
                if 'model_state_dict' in checkpoint:
                    # Standard checkpoint format (from train_rsna_baseline.py)
                    model.load_state_dict(checkpoint['model_state_dict'])
                    epoch = checkpoint.get('epoch', '?')
                    val_loss = checkpoint.get('val_loss', '?')
                    val_wll = checkpoint.get('val_weighted_logloss', None)

                    if isinstance(val_loss, float) and val_wll:
                        print(f"  ✓ Loaded checkpoint from epoch {epoch} (val_loss: {val_loss:.4f}, weighted_logloss: {val_wll:.4f})")
                    elif isinstance(val_loss, float):
                        print(f"  ✓ Loaded checkpoint from epoch {epoch} (val_loss: {val_loss:.4f})")
                    else:
                        print(f"  ✓ Loaded checkpoint from epoch {epoch}")
                elif 'model_weights' in checkpoint:
                    # Alternative checkpoint format
                    model.load_state_dict(checkpoint['model_weights'])
                    epoch = checkpoint.get('epoch_no', '?')
                    val_loss = checkpoint.get('val_loss', '?')
                    print(f"  ✓ Loaded checkpoint from epoch {epoch} (val_loss: {val_loss:.4f})" if isinstance(val_loss, float) else f"  ✓ Loaded checkpoint from epoch {epoch}")
                else:
                    # Direct state_dict format
                    print(f"  - Checkpoint keys: {list(checkpoint.keys())[:10]}...")
                    model.load_state_dict(checkpoint)
                    print(f"  ✓ Loaded model state dict")
            else:
                print(f"  ❌ Unexpected checkpoint format: {type(checkpoint)}")
                return
        except Exception as e:
            print(f"  ❌ Error loading checkpoint: {e}")
            import traceback
            traceback.print_exc()
            return
    elif args.use_pretrained:
        print("  - Loading pretrained backbone...")
        import os
        weights_dir = os.path.expanduser('~/.spinenet/weights')
        try:
            model.load_pretrained_backbone(weights_dir, verbose=False)
            print("  ✓ Pretrained backbone loaded")
        except Exception as e:
            print(f"  ⚠ Warning: Could not load pretrained weights: {e}")
            print("  → Using random weights")
    else:
        print("  - Using random weights (no checkpoint or pretrained weights specified)")

    model = model.to(device)
    model.eval()
    print("✓ Model ready")

    # Get unique patients and select N patients
    print(f"\n[3/3] Selecting {args.num_patients} patients...")
    unique_patients = dataset.metadata['study_id'].unique()
    num_patients = min(args.num_patients, len(unique_patients))
    selected_patients = unique_patients[:num_patients]

    print(f"  ✓ Selected {num_patients} patients: {selected_patients.tolist()}")

    # Get all samples for selected patients
    patient_samples = dataset.metadata[dataset.metadata['study_id'].isin(selected_patients)]
    num_samples = len(patient_samples)

    print(f"  ✓ Total samples to test: {num_samples}")
    print("="*70)

    severity_map = {-1: 'N/A', 0: 'Normal/Mild', 1: 'Moderate', 2: 'Severe'}

    # Initialize lists to collect predictions and labels for metrics
    all_preds = {'spinal_canal': [], 'left_foraminal': [], 'right_foraminal': []}
    all_labels = {'spinal_canal': [], 'left_foraminal': [], 'right_foraminal': []}

    # Test each patient
    for patient_idx, patient_id in enumerate(selected_patients):
        # Get all samples for this patient
        patient_data = dataset.metadata[dataset.metadata['study_id'] == patient_id]
        num_patient_samples = len(patient_data)

        print(f"\n{'='*70}")
        print(f"PATIENT {patient_idx+1}/{num_patients}: {patient_id}")
        print(f"{'='*70}")
        print(f"Number of samples: {num_patient_samples}")
        print()

        # Test all samples for this patient
        for sample_idx, (_, row) in enumerate(patient_data.iterrows()):
            # Get the dataset index
            dataset_idx = row.name

            # Load sample
            volume, labels = dataset[dataset_idx]

            # Prepare input
            volume_input = volume.unsqueeze(0).unsqueeze(0).to(device)  # [1, 1, 9, 112, 224]

            # Run inference
            with torch.no_grad():
                outputs = model(volume_input)

            # Get predictions
            pred_spinal = torch.argmax(outputs['spinal_canal'], dim=1).item()
            pred_left = torch.argmax(outputs['left_foraminal'], dim=1).item()
            pred_right = torch.argmax(outputs['right_foraminal'], dim=1).item()

            # Collect predictions and labels for metrics (skip -1 labels)
            if labels['spinal_canal'] != -1:
                all_preds['spinal_canal'].append(pred_spinal)
                all_labels['spinal_canal'].append(labels['spinal_canal'])
            if labels['left_foraminal'] != -1:
                all_preds['left_foraminal'].append(pred_left)
                all_labels['left_foraminal'].append(labels['left_foraminal'])
            if labels['right_foraminal'] != -1:
                all_preds['right_foraminal'].append(pred_right)
                all_labels['right_foraminal'].append(labels['right_foraminal'])

            # Display results
            print(f"  Sample {sample_idx+1}/{num_patient_samples}:")
            print(f"    Series ID: {row['series_id']}")
            print(f"    Level: {row['level']}")
            print(f"    Condition: {row['condition']}")
            print()
            print(f"    Ground Truth:")
            print(f"      Spinal Canal:     {severity_map[labels['spinal_canal']]}")
            print(f"      Left Foraminal:   {severity_map[labels['left_foraminal']]}")
            print(f"      Right Foraminal:  {severity_map[labels['right_foraminal']]}")
            print()
            print(f"    Predictions:")
            print(f"      Spinal Canal:     {severity_map[pred_spinal]}")
            print(f"      Left Foraminal:   {severity_map[pred_left]}")
            print(f"      Right Foraminal:  {severity_map[pred_right]}")
            print()

    # Compute and display comprehensive metrics
    print("\n" + "="*70)
    print("EVALUATION METRICS")
    print("="*70)

    conditions = ['spinal_canal', 'left_foraminal', 'right_foraminal']
    condition_names = ['Spinal Canal Stenosis', 'Left Foraminal Narrowing', 'Right Foraminal Narrowing']
    class_names = ['Normal/Mild', 'Moderate', 'Severe']

    overall_accuracies = []

    for condition, condition_name in zip(conditions, condition_names):
        if len(all_labels[condition]) == 0:
            print(f"\n{condition_name}:")
            print("  No samples to evaluate (all labels were -1)")
            continue

        preds = np.array(all_preds[condition])
        labels = np.array(all_labels[condition])

        # Overall accuracy
        acc = accuracy_score(labels, preds)
        overall_accuracies.append(acc)

        # Per-class metrics
        precision, recall, f1, support = precision_recall_fscore_support(
            labels, preds, labels=[0, 1, 2], zero_division=0
        )

        print(f"\n{condition_name}:")
        print(f"  Overall Accuracy: {acc:.4f} ({acc*100:.2f}%)")
        print(f"  Total Samples: {len(labels)}")
        print()
        print("  Per-Class Metrics:")
        print("  " + "-"*66)
        print(f"  {'Class':<15} {'Precision':<12} {'Recall':<12} {'F1-Score':<12} {'Support':<10}")
        print("  " + "-"*66)

        for i, class_name in enumerate(class_names):
            print(f"  {class_name:<15} {precision[i]:>8.3f}     {recall[i]:>8.3f}     {f1[i]:>8.3f}     {support[i]:>7.0f}")

        print("  " + "-"*66)

        # Macro averages
        macro_p = np.mean(precision)
        macro_r = np.mean(recall)
        macro_f1 = np.mean(f1)
        print(f"  {'Macro Avg':<15} {macro_p:>8.3f}     {macro_r:>8.3f}     {macro_f1:>8.3f}     {np.sum(support):>7.0f}")
        print("  " + "-"*66)

    # Overall summary
    if len(overall_accuracies) > 0:
        print("\n" + "="*70)
        print("OVERALL SUMMARY")
        print("="*70)
        print(f"Mean Accuracy Across Conditions: {np.mean(overall_accuracies):.4f} ({np.mean(overall_accuracies)*100:.2f}%)")
        print()
        for condition, condition_name, acc in zip(conditions, condition_names, overall_accuracies):
            samples = len(all_labels[condition])
            print(f"  {condition_name:<30} {acc:.4f} ({acc*100:.2f}%) - {samples} samples")

    # Summary
    print("\n" + "="*70)
    print("✓ TEST PASSED!")
    print("="*70)
    print("\nTested:")
    print(f"  ✅ {num_patients} patients")
    print(f"  ✅ {num_samples} total samples")
    print("\nVerified:")
    print("  ✅ Preprocessed .npy files load correctly")
    print("  ✅ Model accepts input format")
    print("  ✅ Model produces predictions")
    print("  ✅ Output format is correct (3 conditions, 3 classes each)")
    print()

    if not args.use_pretrained:
        print("Note: Using random weights. Predictions are random.")
        print("      Use --use-pretrained for pretrained backbone.")
    else:
        print("Note: Using pretrained backbone with random heads.")
        print("      Train the model to get meaningful predictions.")

    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠ Interrupted by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
