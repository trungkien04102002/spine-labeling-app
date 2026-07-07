import {
  useEffect,
  useRef,
  useState,
  type MutableRefObject,
  type ReactNode,
} from "react";
import {
  RenderingEngine,
  Enums,
  imageLoader,
  cache,
  eventTarget,
  type Types,
} from "@cornerstonejs/core";
import {
  ToolGroupManager,
  addTool,
  StackScrollTool,
  ZoomTool,
  PanTool,
  WindowLevelTool,
  BrushTool,
  segmentation,
  utilities as csToolsUtilities,
  Enums as csToolsEnums,
} from "@cornerstonejs/tools";
import { createNiftiImageIdsAndCacheMetadata } from "@cornerstonejs/nifti-volume-loader";
import { ensureCornerstoneInitialized } from "../../lib/cornerstone";

const { ViewportType } = Enums;
const { MouseBindings, SegmentationRepresentations } = csToolsEnums;

// Mask brush/erase editing is wired but painting on a Cornerstone3D *stack*
// labelmap isn't reliably writing yet; keep it hidden until that's solved.
// Grade editing + versioned save + export (the P3 core loop) are unaffected.
const MASK_EDIT_ENABLED = false;

/** Handle the viewer exposes so a parent can read the edited mask for saving. */
export interface MaskEditApi {
  /** Flat uint8 voxels in slice order (z, y, x), or null if no mask loaded. */
  getMaskVolume: () => Uint8Array | null;
}

/** One legend row: label id, anatomical name, and its rendered RGB color. */
export interface LegendEntry {
  id: number;
  name: string;
  color: [number, number, number];
}

interface Props {
  studyId: string;
  apiBaseUrl: string;
  /** Optional overlay pinned inside the image box (e.g. a PACS-style header). */
  overlay?: ReactNode;
  /** When set, scroll the stack to this slice index (jump-to-disc). */
  targetSlice?: number | null;
  /** Present labelmap labels (id -> name) for the edit label picker. */
  segLabels?: Record<string, string>;
  /** Populated with a handle to read the edited mask (for "Save mask"). */
  editApiRef?: MutableRefObject<MaskEditApi | null>;
  /** Called when the mask is painted/erased (marks the mask dirty). */
  onMaskEdited?: () => void;
  /** Called once the labelmap is rendered, with each label's color (legend). */
  onLegend?: (entries: LegendEntry[]) => void;
}

/**
 * Renders a study's NIfTI as a 2D stack viewport (one image per slice) with
 * wheel slice scroll, left-drag window/level, middle-drag pan, right-drag zoom.
 * If the study has a segmentation mask (from `/infer`), it is overlaid as a
 * labelmap with a visibility toggle and an opacity slider.
 */
export default function CornerstoneViewport({
  studyId,
  apiBaseUrl,
  overlay,
  targetSlice,
  segLabels,
  editApiRef,
  onMaskEdited,
  onLegend,
}: Props) {
  const elementRef = useRef<HTMLDivElement>(null);
  const viewportRef = useRef<Types.IStackViewport | null>(null);
  const engineRef = useRef<RenderingEngine | null>(null);
  const labelmapIdsRef = useRef<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [segAvailable, setSegAvailable] = useState(false);
  const [segVisible, setSegVisible] = useState(true);
  const [segOpacity, setSegOpacity] = useState(0.5);
  const [editMode, setEditMode] = useState(false);
  const [editTool, setEditTool] = useState<"brush" | "erase">("brush");
  const [brushSize, setBrushSize] = useState(10);
  const [activeLabel, setActiveLabel] = useState<number>(0);

  const viewportId = `vp-${studyId}`;
  const segmentationId = `seg-${studyId}`;
  const toolGroupId = `tg-${studyId}`;

  useEffect(() => {
    let cancelled = false;
    let engine: RenderingEngine | undefined;

    const renderingEngineId = `engine-${studyId}`;

    (async () => {
      await ensureCornerstoneInitialized();

      const url = `${apiBaseUrl}/studies/${studyId}/display.nii.gz`;
      const imageIds = await createNiftiImageIdsAndCacheMetadata({ url });
      if (cancelled || !elementRef.current) return;

      engine = new RenderingEngine(renderingEngineId);
      engineRef.current = engine;
      engine.enableElement({
        viewportId,
        element: elementRef.current,
        type: ViewportType.STACK,
      });

      [StackScrollTool, ZoomTool, PanTool, WindowLevelTool, BrushTool].forEach(
        addTool,
      );
      const toolGroup =
        ToolGroupManager.getToolGroup(toolGroupId) ??
        ToolGroupManager.createToolGroup(toolGroupId);
      if (!toolGroup) return;

      toolGroup.addTool(WindowLevelTool.toolName);
      toolGroup.addTool(PanTool.toolName);
      toolGroup.addTool(ZoomTool.toolName);
      toolGroup.addTool(StackScrollTool.toolName);
      // Brush + eraser are the same tool with different strategies.
      toolGroup.addTool(BrushTool.toolName, {
        activeStrategy: "FILL_INSIDE_CIRCLE",
      });
      toolGroup.addViewport(viewportId, renderingEngineId);

      toolGroup.setToolActive(WindowLevelTool.toolName, {
        bindings: [{ mouseButton: MouseBindings.Primary }],
      });
      toolGroup.setToolActive(PanTool.toolName, {
        bindings: [{ mouseButton: MouseBindings.Auxiliary }],
      });
      toolGroup.setToolActive(ZoomTool.toolName, {
        bindings: [{ mouseButton: MouseBindings.Secondary }],
      });
      toolGroup.setToolActive(StackScrollTool.toolName, {
        bindings: [{ mouseButton: MouseBindings.Wheel }],
      });

      const viewport = engine.getViewport(viewportId) as Types.IStackViewport;
      viewportRef.current = viewport;
      // Start on the middle slice (most informative for a sagittal stack).
      await viewport.setStack(imageIds, Math.floor(imageIds.length / 2));
      if (cancelled) return;

      // Overlay the segmentation labelmap if the study has one. The mask is a
      // NIfTI with the same geometry as the display volume, so its per-slice
      // imageIds line up 1:1 with the base stack.
      const maskUrl = `${apiBaseUrl}/studies/${studyId}/mask.nii.gz`;
      const hasMask = (await fetch(maskUrl)).ok;
      if (hasMask && !cancelled) {
        const maskImageIds = await createNiftiImageIdsAndCacheMetadata({
          url: maskUrl,
        });
        if (cancelled) return;
        // A stack-viewport labelmap needs images that are *derived* from the
        // base stack (registered as such in the cache). Load the mask's pixels,
        // create blank derived labelmaps from the base stack, then copy the mask
        // voxels into them slice-by-slice (index-aligned: same NIfTI geometry).
        const maskImages = await Promise.all(
          maskImageIds.map((id) => imageLoader.loadAndCacheImage(id)),
        );
        if (cancelled) return;
        const derivedImages =
          imageLoader.createAndCacheDerivedLabelmapImages(imageIds);
        for (let i = 0; i < derivedImages.length; i++) {
          derivedImages[i].getPixelData().set(maskImages[i].getPixelData());
        }
        const labelmapImageIds = derivedImages.map((img) => img.imageId);
        labelmapIdsRef.current = labelmapImageIds;
        segmentation.addSegmentations([
          {
            segmentationId,
            representation: {
              type: SegmentationRepresentations.Labelmap,
              data: { imageIds: labelmapImageIds },
            },
          },
        ]);
        await segmentation.addLabelmapRepresentationToViewport(viewportId, [
          { segmentationId, type: SegmentationRepresentations.Labelmap },
        ]);
        // The pixel data was written after the images were cached; tell the
        // segmentation machinery so it (re)builds textures and repaints.
        segmentation.triggerSegmentationEvents.triggerSegmentationDataModified(
          segmentationId,
        );
        if (!cancelled) setSegAvailable(true);
      }

      if (cancelled) return;
      // Fit once layout has settled: resize with keepCamera=false recomputes
      // the canvas size and re-centers/scales the image to it.
      requestAnimationFrame(() => {
        if (cancelled || !engine) return;
        engine.resize(true, false);
        viewport.render();
      });
    })().catch((err: unknown) => {
      if (!cancelled) {
        setError(err instanceof Error ? err.message : String(err));
      }
    });

    return () => {
      cancelled = true;
      viewportRef.current = null;
      engineRef.current = null;
      labelmapIdsRef.current = [];
      segmentation.removeSegmentation(segmentationId);
      ToolGroupManager.destroyToolGroup(toolGroupId);
      engine?.destroy();
    };
  }, [studyId, apiBaseUrl, viewportId, segmentationId, toolGroupId]);

  // Re-fit the image whenever the viewport box resizes (window resize, layout
  // reflow when the grade panel wraps below on narrow screens, etc.).
  useEffect(() => {
    const el = elementRef.current;
    if (!el) return;
    const observer = new ResizeObserver(() => {
      const engine = engineRef.current;
      if (!engine) return;
      engine.resize(true, false);
      viewportRef.current?.render();
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // Expose a handle to read the edited labelmap voxels (for "Save mask").
  useEffect(() => {
    if (!editApiRef) return;
    editApiRef.current = {
      getMaskVolume: () => {
        const ids = labelmapIdsRef.current;
        if (ids.length === 0) return null;
        const first = cache.getImage(ids[0]);
        if (!first) return null;
        const per = first.getPixelData().length;
        const out = new Uint8Array(ids.length * per);
        ids.forEach((id, i) => {
          const img = cache.getImage(id);
          if (img) out.set(Uint8Array.from(img.getPixelData()), i * per);
        });
        return out;
      },
    };
    return () => {
      if (editApiRef) editApiRef.current = null;
    };
  }, [editApiRef, segAvailable]);

  // Toggle between review (window/level on primary) and edit (brush on primary).
  useEffect(() => {
    if (!segAvailable) return;
    const toolGroup = ToolGroupManager.getToolGroup(toolGroupId);
    if (!toolGroup) return;
    if (editMode) {
      // The brush paints into the viewport's ACTIVE segmentation/segment.
      segmentation.activeSegmentation.setActiveSegmentation(
        viewportId,
        segmentationId,
      );
      segmentation.segmentIndex.setActiveSegmentIndex(segmentationId, activeLabel);
      toolGroup.setToolConfiguration(BrushTool.toolName, {
        activeStrategy:
          editTool === "erase" ? "ERASE_INSIDE_CIRCLE" : "FILL_INSIDE_CIRCLE",
      });
      toolGroup.setToolActive(BrushTool.toolName, {
        bindings: [{ mouseButton: MouseBindings.Primary }],
      });
      csToolsUtilities.segmentation.setBrushSizeForToolGroup(toolGroupId, brushSize);
    } else {
      toolGroup.setToolPassive(BrushTool.toolName);
      toolGroup.setToolActive(WindowLevelTool.toolName, {
        bindings: [{ mouseButton: MouseBindings.Primary }],
      });
    }
  }, [
    segAvailable,
    editMode,
    editTool,
    brushSize,
    activeLabel,
    segmentationId,
    toolGroupId,
  ]);

  // Build the color legend once the labelmap is rendered (colors are assigned
  // by Cornerstone's LUT keyed on the label id = segment index).
  useEffect(() => {
    if (!segAvailable || !segLabels || !onLegend) return;
    const entries: LegendEntry[] = Object.entries(segLabels).map(
      ([id, name]) => {
        const c = segmentation.config.color.getSegmentIndexColor(
          viewportId,
          segmentationId,
          Number(id),
        );
        return { id: Number(id), name, color: [c[0], c[1], c[2]] };
      },
    );
    onLegend(entries);
  }, [segAvailable, segLabels, onLegend, viewportId, segmentationId]);

  // Mark the mask dirty when the user paints/erases. Only while editing, so the
  // initial setup's triggerSegmentationDataModified doesn't count as an edit.
  useEffect(() => {
    if (!onMaskEdited || !editMode) return;
    const handler = () => onMaskEdited();
    eventTarget.addEventListener(
      csToolsEnums.Events.SEGMENTATION_DATA_MODIFIED,
      handler,
    );
    return () =>
      eventTarget.removeEventListener(
        csToolsEnums.Events.SEGMENTATION_DATA_MODIFIED,
        handler,
      );
  }, [onMaskEdited, editMode]);

  // Default the active edit label to the first present label once seg loads.
  useEffect(() => {
    if (segAvailable && activeLabel === 0 && segLabels) {
      const first = Object.keys(segLabels)[0];
      if (first) setActiveLabel(Number(first));
    }
  }, [segAvailable, segLabels, activeLabel]);

  // Jump the stack to a requested slice (e.g. clicking a disc in the grade table).
  useEffect(() => {
    const viewport = viewportRef.current;
    if (viewport == null || targetSlice == null) return;
    const count = viewport.getImageIds().length;
    const index = Math.min(Math.max(Math.round(targetSlice), 0), count - 1);
    viewport.setImageIdIndex(index);
    viewport.render();
  }, [targetSlice]);

  // Apply visibility toggle whenever it changes (once the seg is present).
  useEffect(() => {
    if (!segAvailable) return;
    segmentation.config.visibility.setSegmentationRepresentationVisibility(
      viewportId,
      { segmentationId, type: SegmentationRepresentations.Labelmap },
      segVisible,
    );
  }, [segAvailable, segVisible, viewportId, segmentationId]);

  // Apply opacity (fillAlpha) whenever the slider changes.
  useEffect(() => {
    if (!segAvailable) return;
    segmentation.config.style.setStyle(
      {
        type: SegmentationRepresentations.Labelmap,
        viewportId,
        segmentationId,
      },
      { fillAlpha: segOpacity },
    );
  }, [segAvailable, segOpacity, viewportId, segmentationId]);

  return (
    <div>
      {error && <p style={{ color: "crimson" }}>Viewer error: {error}</p>}
      {segAvailable && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "1rem",
            marginBottom: "0.5rem",
            flexWrap: "wrap",
            whiteSpace: "nowrap",
          }}
        >
          <label>
            <input
              type="checkbox"
              checked={segVisible}
              onChange={(e) => setSegVisible(e.target.checked)}
            />{" "}
            Segmentation
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            Opacity
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={segOpacity}
              disabled={!segVisible}
              onChange={(e) => setSegOpacity(Number(e.target.value))}
            />
          </label>
          {MASK_EDIT_ENABLED && (
            <label>
              <input
                type="checkbox"
                checked={editMode}
                onChange={(e) => setEditMode(e.target.checked)}
              />{" "}
              Edit mask
            </label>
          )}
          {MASK_EDIT_ENABLED && editMode && (
            <>
              <select
                value={editTool}
                onChange={(e) => setEditTool(e.target.value as "brush" | "erase")}
              >
                <option value="brush">Brush</option>
                <option value="erase">Erase</option>
              </select>
              <label
                style={{ display: "flex", alignItems: "center", gap: "0.25rem" }}
              >
                Size
                <input
                  type="range"
                  min={1}
                  max={40}
                  value={brushSize}
                  onChange={(e) => setBrushSize(Number(e.target.value))}
                />
              </label>
              {segLabels && (
                <select
                  value={activeLabel}
                  onChange={(e) => setActiveLabel(Number(e.target.value))}
                  disabled={editTool === "erase"}
                >
                  {Object.entries(segLabels).map(([id, name]) => (
                    <option key={id} value={id}>
                      {name}
                    </option>
                  ))}
                </select>
              )}
            </>
          )}
        </div>
      )}
      <div style={{ position: "relative" }}>
        <div
          ref={elementRef}
          onContextMenu={(e) => e.preventDefault()}
          style={{
            position: "relative",
            width: "100%",
            // Responsive: scale with the viewport but stay in a sane range.
            height: "min(72vh, 640px)",
            minHeight: "360px",
            background: "black",
            overflow: "hidden",
            // The app root sets text-align:center; that shifts Cornerstone's
            // absolutely-positioned canvas. Reset it so the canvas fills the box.
            textAlign: "left",
          }}
        />
        {overlay}
      </div>
    </div>
  );
}
