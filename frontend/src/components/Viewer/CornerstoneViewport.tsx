import {
  useEffect,
  useRef,
  useState,
  type MutableRefObject,
  type ReactNode,
} from "react";
import {
  RenderingEngine,
  getRenderingEngine,
  Enums,
  imageLoader,
  cache,
  eventTarget,
  metaData,
  utilities as csUtilities,
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
  CircleScissorsTool,
  RectangleScissorsTool,
  segmentation,
  utilities as csToolsUtilities,
  Enums as csToolsEnums,
} from "@cornerstonejs/tools";
import { createNiftiImageIdsAndCacheMetadata } from "@cornerstonejs/nifti-volume-loader";
import { ensureCornerstoneInitialized } from "../../lib/cornerstone";
import { useT } from "../../lib/i18n";
import {
  MASK_HISTORY_DEPTH,
  maskHistoryDepth,
  redoMaskEdit,
  resetMaskHistory,
  undoMaskEdit,
} from "../../lib/maskHistory";
import { useStructureName } from "../../lib/labels";
import LabelPicker, { Swatch } from "./LabelPicker";

const { ViewportType } = Enums;
const { MouseBindings, SegmentationRepresentations } = csToolsEnums;

/** Shape of the gesture that edits voxels. Each fills or erases, never both. */
type EditShape = "brush" | "circle" | "rect";
type EditAction = "paint" | "erase";

/**
 * How much thicker the selected structure's outline is drawn than the others.
 * This is how "what am I about to paint into?" is answered on the image itself
 * rather than only in the toolbar.
 */
const ACTIVE_OUTLINE_DELTA = 3;

/** Cornerstone tool that draws each shape. */
function shapeToolName(shape: EditShape): string {
  if (shape === "circle") return CircleScissorsTool.toolName;
  if (shape === "rect") return RectangleScissorsTool.toolName;
  return BrushTool.toolName;
}

/**
 * Fill/erase is a *strategy* on the tool, not a separate tool. The brush and
 * the scissors spell their strategies differently, which is the only reason
 * this mapping exists.
 */
function strategyFor(shape: EditShape, action: EditAction): string {
  if (shape === "brush") {
    return action === "erase" ? "ERASE_INSIDE_CIRCLE" : "FILL_INSIDE_CIRCLE";
  }
  return action === "erase" ? "ERASE_INSIDE" : "FILL_INSIDE";
}

const EVERY_EDIT_TOOL = [
  BrushTool.toolName,
  CircleScissorsTool.toolName,
  RectangleScissorsTool.toolName,
];

// Mask brush/erase editing on the stack labelmap (paint requires window/level
// to be passive so the primary button reaches the brush).
const MASK_EDIT_ENABLED = true;

/**
 * One colour per structure, chosen so that neighbours down the spine never
 * look alike. Cornerstone's default table gave adjacent vertebrae and discs
 * near-identical hues, and clinicians mistook one for the next. Ids are
 * TotalSpineSeg's; colours alternate warm/cool along the column (cord, canal,
 * then T10, disc, T11, disc, ... sacrum). Unlisted ids cycle through FALLBACK.
 */
const STRUCTURE_COLORS: Record<number, [number, number, number]> = {
  1: [240, 50, 230], // spinal cord - magenta
  2: [66, 212, 244], // spinal canal - cyan
  30: [145, 30, 180], // T10 - purple
  81: [191, 239, 69], // disc T10-T11 - lime
  31: [67, 99, 216], // T11 - blue
  82: [255, 225, 25], // disc T11-T12 - yellow
  32: [170, 40, 40], // T12 - maroon
  91: [170, 255, 195], // disc T12-L1 - mint
  41: [230, 25, 75], // L1 - red
  92: [255, 216, 177], // disc L1-L2 - apricot
  42: [60, 180, 75], // L2 - green
  93: [245, 130, 49], // disc L2-L3 - orange
  43: [70, 153, 144], // L3 - teal
  94: [255, 250, 200], // disc L3-L4 - beige
  44: [154, 99, 36], // L4 - brown
  95: [220, 190, 255], // disc L4-L5 - lavender
  45: [128, 128, 0], // L5 - olive
  100: [250, 190, 212], // disc L5-S1 - pink
  50: [169, 169, 169], // sacrum - grey
};
const FALLBACK_COLORS: [number, number, number][] = [
  [230, 25, 75], [60, 180, 75], [255, 225, 25], [67, 99, 216], [245, 130, 49],
  [145, 30, 180], [66, 212, 244], [240, 50, 230], [191, 239, 69], [250, 190, 212],
  [70, 153, 144], [220, 190, 255], [154, 99, 36], [255, 250, 200], [128, 0, 0],
  [170, 255, 195], [128, 128, 0], [255, 216, 177], [0, 0, 117], [169, 169, 169],
];
function structureColor(id: number): [number, number, number] {
  return STRUCTURE_COLORS[id] ?? FALLBACK_COLORS[id % FALLBACK_COLORS.length];
}
const VIEW_BTN =
  "rounded-md border border-slate-300 bg-white px-2 py-1 font-semibold text-slate-700 transition hover:border-teal-400 hover:bg-teal-50 disabled:opacity-30";

/**
 * Re-place every slice along the true slice normal, one slice thickness apart.
 *
 * @cornerstonejs/nifti-volume-loader 5.2.1 steps slice i from the origin by
 * `direction[6 + k] * spacing[k]` on each axis k -- the in-plane pixel size
 * where the slice spacing belongs. For an axial series the error lands on an
 * axis that barely matters; for a sagittal one the slices end up 0.44 mm apart
 * instead of 5.6 mm, and the camera's thin clipping slab then misses the image:
 * the viewport shows black, or (a slightly oblique series) only the band where
 * the tilted image crosses the slab. Hit on a clinician's Siemens export
 * (2026-10-02): sagittal T2, STIR and T1 all broken, axial and coronal fine.
 */
function fixNiftiSlicePositions(imageIds: string[]): void {
  if (imageIds.length === 0) return;
  type Plane = {
    rowCosines: number[];
    columnCosines: number[];
    imagePositionPatient: number[];
    sliceThickness: number;
  };
  const first = metaData.get("imagePlaneModule", imageIds[0]) as Plane | undefined;
  if (!first?.rowCosines || !first.columnCosines || !first.imagePositionPatient) return;
  const [r, c] = [first.rowCosines, first.columnCosines];
  let n = [r[1] * c[2] - r[2] * c[1], r[2] * c[0] - r[0] * c[2], r[0] * c[1] - r[1] * c[0]];
  const len = Math.hypot(n[0], n[1], n[2]) || 1;
  n = n.map((v) => v / len);
  // Keep the loader's stacking direction: only the step length is wrong.
  if (imageIds.length > 1) {
    const second = metaData.get("imagePlaneModule", imageIds[1]) as Plane | undefined;
    if (second?.imagePositionPatient) {
      const d = second.imagePositionPatient.map((v, k) => v - first.imagePositionPatient[k]);
      if (d[0] * n[0] + d[1] * n[1] + d[2] * n[2] < 0) n = n.map((v) => -v);
    }
  }
  const step = first.sliceThickness || 1;
  const origin = first.imagePositionPatient;
  imageIds.forEach((id, i) => {
    const plane = metaData.get("imagePlaneModule", id) as Plane | undefined;
    if (!plane) return;
    const ipp = origin.map((v, k) => v + n[k] * step * i);
    csUtilities.genericMetadataProvider.add(id, {
      type: "imagePlaneModule",
      metadata: { ...plane, imagePositionPatient: ipp },
    });
  });
}

/**
 * One rendering engine for the whole app, reused by every viewer mount.
 *
 * Each RenderingEngine holds a WebGL context, and destroying one does not hand
 * its context back promptly. Opening a few studies and switching series made a
 * new engine every time; past Chrome's limit (~16) the browser drops the
 * oldest context -- sometimes the one on screen -- and the image goes black,
 * with "Too many active WebGL contexts" in the console. Seen on the GPU box
 * 2026-10-02 on about half of all loads.
 */
const ENGINE_ID = "spine-viewer-engine";
function sharedEngine(): RenderingEngine {
  return (getRenderingEngine(ENGINE_ID) as RenderingEngine | undefined) ?? new RenderingEngine(ENGINE_ID);
}

/** 1st-99.5th percentile of the slice on screen, or null if there is none. */
function robustWindow(viewport: Types.IStackViewport): { lower: number; upper: number } | null {
  const pixels = cache.getImage(viewport.getCurrentImageId())?.getPixelData();
  if (!pixels || pixels.length === 0) return null;
  // A strided sample is plenty for two percentiles and keeps this instant.
  const stride = Math.max(1, Math.floor(pixels.length / 50000));
  const sample: number[] = [];
  for (let i = 0; i < pixels.length; i += stride) sample.push(pixels[i]);
  sample.sort((a, b) => a - b);
  const at = (q: number) => sample[Math.min(sample.length - 1, Math.floor(q * sample.length))];
  const lower = at(0.01);
  const upper = at(0.995);
  return upper > lower ? { lower, upper } : null;
}

/** Brush radius a session starts with: small, so a first stroke cannot flood a neighbour. */
const DEFAULT_BRUSH_SIZE = 3;

/** Handle the viewer exposes so a parent can read the edited mask for saving. */
export interface MaskEditApi {
  /** Flat uint8 voxels in slice order (z, y, x), or null if no mask loaded. */
  getMaskVolume: () => Uint8Array | null;
  /** Undo one brush/erase stroke. False when there is nothing left to undo. */
  undoStroke: () => boolean;
  /** Redo one undone stroke. False when there is nothing ahead. */
  redoStroke: () => boolean;
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
  /**
   * Identifies which series is being shown. `display.nii.gz` serves whichever
   * series is active, so switching series keeps the URL but changes the bytes;
   * this value is appended as a query param to give the new volume its own
   * cache key (Cornerstone caches volumes by URL) and to re-run the loader.
   */
  seriesKey?: string | number | null;
  /** Change it to reload image + labelmap, e.g. after a grading run wrote a new mask. */
  reloadKey?: unknown;
  /** Optional overlay pinned inside the image box (e.g. a PACS-style header). */
  overlay?: ReactNode;
  /** When set, scroll the stack to this slice index (jump-to-disc). */
  targetSlice?: number | null;
  /** Present labelmap labels (id -> name) for the edit label picker. */
  segLabels?: Record<string, string>;
  /** Hide mask editing (e.g. while a grading run is still writing the mask). */
  editDisabled?: boolean;
  /**
   * Mask editing is controlled by the page, not by this component, so the
   * Structures panel beside the image can act as the brush's picker and the
   * page's Undo/Redo buttons can reach the strokes painted here.
   */
  editMode?: boolean;
  onEditModeChange?: (on: boolean) => void;
  /** Segment the brush paints. null = not chosen yet; the brush stays inert. */
  activeLabel?: number | null;
  onActiveLabelChange?: (id: number) => void;
  /** Populated with a handle to read the edited mask (for "Save mask"). */
  editApiRef?: MutableRefObject<MaskEditApi | null>;
  /** Undo/redo the page's single edit timeline, so the toolbar and the grades
   *  panel drive the same history rather than two competing ones. */
  onUndo?: () => void;
  onRedo?: () => void;
  canUndo?: boolean;
  canRedo?: boolean;
  /** What the next undo would revert, for the button's label. */
  undoLabel?: string;
  /** Save the study's pending edits, so a mask edit can be saved from the
   *  toolbar rather than from the panel below the image. */
  onSave?: () => void;
  canSave?: boolean;
  saveLabel?: string;
  /** Called once per completed stroke (mouse-down to mouse-up), not per move. */
  onMaskStroke?: () => void;
  /** Called when a fresh labelmap loads and the stroke history is dropped. */
  onMaskHistoryReset?: () => void;
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
  seriesKey,
  reloadKey,
  overlay,
  targetSlice,
  segLabels,
  editDisabled,
  editMode = false,
  onEditModeChange,
  activeLabel = null,
  onActiveLabelChange,
  editApiRef,
  onUndo,
  onRedo,
  canUndo,
  canRedo,
  undoLabel,
  onSave,
  canSave,
  saveLabel,
  onMaskStroke,
  onMaskHistoryReset,
  onLegend,
}: Props) {
  const { t } = useT();
  const structureName = useStructureName();
  const elementRef = useRef<HTMLDivElement>(null);
  const viewportRef = useRef<Types.IStackViewport | null>(null);
  const engineRef = useRef<RenderingEngine | null>(null);
  const labelmapIdsRef = useRef<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  // Set when a mask exists but belongs to a different acquisition than the one
  // on screen -- a fact worth stating, not an error.
  const [segForeign, setSegForeign] = useState(false);
  const [segAvailable, setSegAvailable] = useState(false);
  const [segVisible, setSegVisible] = useState(true);
  const [segOpacity, setSegOpacity] = useState(0.5);
  const [editShape, setEditShape] = useState<EditShape>("brush");
  const [editAction, setEditAction] = useState<EditAction>("paint");
  const [brushSize, setBrushSize] = useState(DEFAULT_BRUSH_SIZE);
  // "Point at it" mode: the next click on the image chooses the structure the
  // edit tools work on, instead of painting.
  const [picking, setPicking] = useState(false);
  // The structure under the cursor while picking, and whether the last click
  // landed on background. Both are read-outs only; neither changes the mask.
  const [hoverLabel, setHoverLabel] = useState<number | null>(null);
  const [pickMissed, setPickMissed] = useState(false);
  // Legend entries are kept here as well as handed to the page: the label
  // picker needs each structure's *rendered* color, which only the LUT knows.
  const [legendEntries, setLegendEntries] = useState<LegendEntry[]>([]);
  // Viewing controls with buttons, for readers who do not know the mouse
  // bindings: slice position, zoom, brightness/contrast, and a way back.
  const [sliceIndex, setSliceIndex] = useState(0);
  const [sliceCount, setSliceCount] = useState(0);
  const [brightness, setBrightness] = useState(0); // -100..100
  const [contrast, setContrast] = useState(0); // -100..100
  const baseVoiRef = useRef<{ lower: number; upper: number } | null>(null);
  // A gesture spans many mousemove events; these track it so the page is told
  // "one edit happened", matching one entry in Cornerstone's undo history.
  const paintingRef = useRef(false);
  const strokeTouchedRef = useRef(false);
  // Undo depth at mouse-down. The page only gets a step if this grew.
  const depthAtDownRef = useRef(0);
  // Read inside the load effect, which must not re-run when a parent re-renders.
  const historyResetRef = useRef(onMaskHistoryReset);
  historyResetRef.current = onMaskHistoryReset;

  const viewportId = `vp-${studyId}`;
  const segmentationId = `seg-${studyId}`;
  const toolGroupId = `tg-${studyId}`;

  // Pointing wins over painting: while it is armed the primary button chooses a
  // structure instead of changing voxels. It arms on request, and by itself
  // when nothing is chosen yet -- the moment the brush would refuse to paint
  // anyway, so the doctor's first click on the image does something useful.
  const pickArmed =
    editMode &&
    segAvailable &&
    (picking || (editAction === "paint" && activeLabel == null));
  // Painting with no structure chosen is what put the wrong colour on the image
  // in the first place, so a fill tool is only armed once one is picked.
  // Erasing needs no target, so it arms immediately.
  const editArmed =
    editMode &&
    segAvailable &&
    !pickArmed &&
    (editAction === "erase" || activeLabel != null);
  /** Structure under the cursor while pointing, named and coloured. */
  const hoverEntry =
    hoverLabel == null
      ? null
      : (legendEntries.find((e) => e.id === hoverLabel) ?? null);

  useEffect(() => {
    let cancelled = false;
    let engine: RenderingEngine | undefined;

    const renderingEngineId = ENGINE_ID;

    // Each series gets a fresh verdict: a failure on one must not be left on
    // screen while a later, working one renders underneath it.
    setError(null);
    setSegForeign(false);
    setSegAvailable(false);

    (async () => {
      await ensureCornerstoneInitialized();

      const url =
        `${apiBaseUrl}/studies/${studyId}/display.nii.gz` +
        (seriesKey == null ? "" : `?series=${seriesKey}`);
      const imageIds = await createNiftiImageIdsAndCacheMetadata({ url });
      if (cancelled || !elementRef.current) return;
      fixNiftiSlicePositions(imageIds);

      engine = sharedEngine();
      engineRef.current = engine;
      engine.enableElement({
        viewportId,
        element: elementRef.current,
        type: ViewportType.STACK,
      });

      [
        StackScrollTool,
        ZoomTool,
        PanTool,
        WindowLevelTool,
        BrushTool,
        CircleScissorsTool,
        RectangleScissorsTool,
      ].forEach(addTool);
      const toolGroup =
        ToolGroupManager.getToolGroup(toolGroupId) ??
        ToolGroupManager.createToolGroup(toolGroupId);
      if (!toolGroup) return;

      toolGroup.addTool(WindowLevelTool.toolName);
      toolGroup.addTool(PanTool.toolName);
      toolGroup.addTool(ZoomTool.toolName);
      toolGroup.addTool(StackScrollTool.toolName);
      // Brush + eraser are the same tool with different strategies, and so are
      // the two region tools: draw a shape, fill or erase everything inside it.
      toolGroup.addTool(BrushTool.toolName, {
        activeStrategy: "FILL_INSIDE_CIRCLE",
      });
      toolGroup.addTool(CircleScissorsTool.toolName, {
        activeStrategy: "FILL_INSIDE",
      });
      toolGroup.addTool(RectangleScissorsTool.toolName, {
        activeStrategy: "FILL_INSIDE",
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
      // Read-only handle for diagnosing a viewer on a remote box (DevTools).
      (window as unknown as { __spineViewer?: unknown }).__spineViewer = { viewport, imageIds };
      // Start on the middle slice (most informative for a sagittal stack).
      await viewport.setStack(imageIds, Math.floor(imageIds.length / 2));
      if (cancelled) return;
      // Start from the window a reader would set, not the full min-max range:
      // a few saturated pixels (4095 in a STIR whose tissue sits under 500)
      // otherwise leave the whole picture near black.
      const voi = robustWindow(viewport) ?? viewport.getProperties().voiRange;
      if (voi) viewport.setProperties({ voiRange: { lower: voi.lower, upper: voi.upper } });
      baseVoiRef.current = voi ? { lower: voi.lower, upper: voi.upper } : null;
      setSliceCount(imageIds.length);
      setSliceIndex(viewport.getCurrentImageIdIndex());
      setBrightness(0);
      setContrast(0);

      // Overlay the segmentation labelmap if the study has one. The mask is a
      // NIfTI with the same geometry as the display volume, so its per-slice
      // imageIds line up 1:1 with the base stack.
      const maskUrl = `${apiBaseUrl}/studies/${studyId}/mask.nii.gz?v=${Date.now()}`;
      const hasMask = (await fetch(maskUrl, { cache: "no-store" })).ok;
      if (hasMask && !cancelled) {
        const maskImageIds = await createNiftiImageIdsAndCacheMetadata({
          url: maskUrl,
        });
        fixNiftiSlicePositions(maskImageIds);
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
        // The mask belongs to whichever series the AI ran on. Browsing a
        // different acquisition (axial vs sagittal) hands us a labelmap of a
        // different shape; copying it in would throw "offset is out of bounds"
        // and, worse, a same-sized-but-different series would silently paint
        // one acquisition's anatomy onto another's.
        const fitsThisSeries =
          maskImages.length === derivedImages.length &&
          maskImages.every(
            (img, i) =>
              img.getPixelData().length ===
              derivedImages[i].getPixelData().length,
          );
        if (!fitsThisSeries) {
          setSegForeign(true);
        } else {
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
          for (let id = 1; id < 256; id++) {
            const [r, g, b] = structureColor(id);
            segmentation.config.color.setSegmentIndexColor(
              viewportId,
              segmentationId,
              id,
              [r, g, b, 255],
            );
          }
          // The pixel data was written after the images were cached; tell the
          // segmentation machinery so it (re)builds textures and repaints.
          segmentation.triggerSegmentationEvents.triggerSegmentationDataModified(
            segmentationId,
          );
          // Strokes recorded against the previous labelmap can only be replayed
          // into voxels that no longer exist, so this labelmap starts with an
          // empty history -- and the page has to forget its mask steps too.
          resetMaskHistory();
          historyResetRef.current?.();
          if (!cancelled) setSegAvailable(true);
        }
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
      resetMaskHistory();
      historyResetRef.current?.();
      segmentation.removeSegmentation(segmentationId);
      ToolGroupManager.destroyToolGroup(toolGroupId);
      // Detach, never destroy: the engine and its WebGL context are shared.
      try {
        engine?.disableElement(viewportId);
      } catch {
        /* already gone */
      }
    };
  }, [studyId, apiBaseUrl, seriesKey, reloadKey, viewportId, segmentationId, toolGroupId]);

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
      // Replaying a memo writes the old voxel values back and fires
      // SEGMENTATION_DATA_MODIFIED, which rebuilds the texture; the explicit
      // render is belt-and-braces for the slice already on screen.
      undoStroke: () => {
        const done = undoMaskEdit();
        if (done) viewportRef.current?.render();
        return done;
      },
      redoStroke: () => {
        const done = redoMaskEdit();
        if (done) viewportRef.current?.render();
        return done;
      },
    };
    return () => {
      if (editApiRef) editApiRef.current = null;
    };
  }, [editApiRef, segAvailable]);

  // Keep Cornerstone's active segment in step with the page's choice at all
  // times -- not only while a tool is armed -- because the labelmap draws the
  // *active* segment with a thicker outline. That outline is how the doctor
  // sees what is selected, and it has to appear whichever of the three ways
  // made the choice: clicking the image, the toolbar picker, or the legend.
  useEffect(() => {
    if (!segAvailable) return;
    segmentation.activeSegmentation.setActiveSegmentation(
      viewportId,
      segmentationId,
    );
    if (activeLabel == null) return;
    segmentation.segmentIndex.setActiveSegmentIndex(segmentationId, activeLabel);
    viewportRef.current?.render();
  }, [segAvailable, activeLabel, viewportId, segmentationId]);

  // Toggle between review (window/level on primary), pointing (a click chooses
  // a structure) and editing (the chosen shape tool on primary).
  useEffect(() => {
    if (!segAvailable) return;
    const toolGroup = ToolGroupManager.getToolGroup(toolGroupId);
    if (!toolGroup) return;
    if (editArmed) {
      // Free the primary button from window/level so the edit tool receives it.
      toolGroup.setToolPassive(WindowLevelTool.toolName);
      const armedTool = shapeToolName(editShape);
      EVERY_EDIT_TOOL.filter((name) => name !== armedTool).forEach((name) =>
        toolGroup.setToolPassive(name),
      );
      toolGroup.setToolConfiguration(armedTool, {
        activeStrategy: strategyFor(editShape, editAction),
      });
      toolGroup.setToolActive(armedTool, {
        bindings: [{ mouseButton: MouseBindings.Primary }],
      });
      if (editShape === "brush") {
        csToolsUtilities.segmentation.setBrushSizeForToolGroup(
          toolGroupId,
          brushSize,
        );
      }
    } else {
      EVERY_EDIT_TOOL.forEach((name) => toolGroup.setToolPassive(name));
      if (editMode) {
        // Editing, but pointing at a structure or waiting for one to be chosen:
        // leave the primary button bound to nothing. Handing it back to
        // window/level would mean a doctor who drags expecting to paint instead
        // silently re-windows the image. The pick listener below reads the
        // click straight off the element.
        toolGroup.setToolPassive(WindowLevelTool.toolName);
      } else {
        toolGroup.setToolActive(WindowLevelTool.toolName, {
          bindings: [{ mouseButton: MouseBindings.Primary }],
        });
      }
    }
  }, [
    segAvailable,
    editMode,
    editArmed,
    editShape,
    editAction,
    brushSize,
    toolGroupId,
  ]);

  // Draw the selected structure with a fatter outline than its neighbours.
  useEffect(() => {
    if (!segAvailable) return;
    segmentation.config.style.setStyle(
      {
        type: SegmentationRepresentations.Labelmap,
        viewportId,
        segmentationId,
      },
      { activeSegmentOutlineWidthDelta: ACTIVE_OUTLINE_DELTA },
    );
  }, [segAvailable, viewportId, segmentationId]);

  // Click the image to choose the structure to work on.
  //
  // This is deliberately not Cornerstone's `SegmentSelectTool`: that tool acts
  // on *hover*, so merely moving the mouse across the image would re-target the
  // brush without the doctor asking. It picks with the same utility underneath;
  // here the hover only reports what is under the cursor, and the click is what
  // commits.
  useEffect(() => {
    if (!pickArmed) return;
    const el = elementRef.current;
    if (!el) return;
    const labelAt = (evt: MouseEvent): number | null => {
      const viewport = viewportRef.current;
      if (!viewport) return null;
      const rect = el.getBoundingClientRect();
      const world = viewport.canvasToWorld([
        evt.clientX - rect.left,
        evt.clientY - rect.top,
      ]);
      const index = csToolsUtilities.segmentation.getSegmentIndexAtWorldPoint(
        segmentationId,
        world,
        { viewport },
      );
      return index && index > 0 ? index : null;
    };
    let frame = 0;
    const onMove = (evt: MouseEvent) => {
      if (frame) return; // one probe per animation frame, not per mousemove
      frame = requestAnimationFrame(() => {
        frame = 0;
        setHoverLabel(labelAt(evt));
      });
    };
    const onClick = (evt: MouseEvent) => {
      if (evt.button !== 0) return;
      const index = labelAt(evt);
      if (index == null) {
        setPickMissed(true);
        return;
      }
      setPickMissed(false);
      onActiveLabelChange?.(index);
      // Pointing is a step on the way to editing, so hand the tool back once
      // the structure is chosen instead of making the doctor leave pick mode.
      setPicking(false);
    };
    el.addEventListener("mousemove", onMove);
    el.addEventListener("click", onClick);
    return () => {
      if (frame) cancelAnimationFrame(frame);
      el.removeEventListener("mousemove", onMove);
      el.removeEventListener("click", onClick);
      setHoverLabel(null);
    };
  }, [pickArmed, segmentationId, onActiveLabelChange]);

  // Build the color legend once the labelmap is rendered (colors are assigned
  // by Cornerstone's LUT keyed on the label id = segment index).
  useEffect(() => {
    if (!segAvailable || !segLabels) return;
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
    setLegendEntries(entries);
    onLegend?.(entries);
  }, [segAvailable, segLabels, onLegend, viewportId, segmentationId]);

  // Report one completed gesture (mouse-down to mouse-up), so the page's undo
  // stack gets one entry per gesture -- the same granularity Cornerstone commits
  // to its own history on mouse-up.
  //
  // The test is Cornerstone's own undo depth, not "did any voxel change". A
  // gesture earns a step on the page's timeline only if it actually left
  // something to undo, which is exactly the guarantee the Undo button makes.
  // Asking the tool instead would happily add a step for an edit that recorded
  // no memo (`PaintFillTool` writes voxels that way, which is why it is not
  // offered here) and Ctrl+Z would then skip over it.
  useEffect(() => {
    if (!onMaskStroke || !editMode || !segAvailable) return;
    const el = elementRef.current;
    if (!el) return;
    // Kept only for the saturated-history case below: once 50 steps are on the
    // ring the depth stops growing, and then "voxels changed" is all there is.
    const onData = () => {
      if (paintingRef.current) strokeTouchedRef.current = true;
    };
    const onDown = () => {
      paintingRef.current = true;
      strokeTouchedRef.current = false;
      depthAtDownRef.current = maskHistoryDepth();
    };
    // On window, not the canvas: a gesture that ends outside the image still ends.
    const onUp = () => {
      if (!paintingRef.current) return;
      paintingRef.current = false;
      const before = depthAtDownRef.current;
      const touched = strokeTouchedRef.current;
      strokeTouchedRef.current = false;
      // The tools commit their memo in their own mouse-up handler -- the brush
      // as the stroke ends, the scissors when they apply the fill. Both run
      // inside the DOM mouse-up dispatch, so read the depth in the next task,
      // once they are done.
      setTimeout(() => {
        const grew = maskHistoryDepth() - before;
        if (grew > 0) {
          for (let i = 0; i < grew; i++) onMaskStroke();
        } else if (touched && before >= MASK_HISTORY_DEPTH) {
          // The ring is full: a new memo pushed the oldest one out instead of
          // making the history deeper. Still one undoable gesture.
          onMaskStroke();
        }
      }, 0);
    };
    eventTarget.addEventListener(
      csToolsEnums.Events.SEGMENTATION_DATA_MODIFIED,
      onData,
    );
    el.addEventListener("mousedown", onDown);
    window.addEventListener("mouseup", onUp);
    return () => {
      eventTarget.removeEventListener(
        csToolsEnums.Events.SEGMENTATION_DATA_MODIFIED,
        onData,
      );
      el.removeEventListener("mousedown", onDown);
      window.removeEventListener("mouseup", onUp);
    };
  }, [onMaskStroke, editMode, segAvailable]);

  // Keep the slice read-out in step with the wheel, the buttons and jumps.
  useEffect(() => {
    const el = elementRef.current;
    if (!el) return;
    const onNewImage = () => {
      const viewport = viewportRef.current;
      if (viewport) setSliceIndex(viewport.getCurrentImageIdIndex());
    };
    el.addEventListener(Enums.Events.STACK_NEW_IMAGE, onNewImage);
    return () => el.removeEventListener(Enums.Events.STACK_NEW_IMAGE, onNewImage);
  }, []);

  // Brightness and contrast as offsets from the image's own starting window,
  // so the sliders always mean the same thing and 0/0 is the original.
  useEffect(() => {
    const viewport = viewportRef.current;
    const base = baseVoiRef.current;
    if (!viewport || !base) return;
    const width0 = base.upper - base.lower;
    const center0 = (base.upper + base.lower) / 2;
    const width = width0 * Math.pow(2, -contrast / 50);
    const center = center0 - (brightness / 100) * width0 * 0.5;
    viewport.setProperties({
      voiRange: { lower: center - width / 2, upper: center + width / 2 },
    });
    viewport.render();
  }, [brightness, contrast]);

  function stepSlice(delta: number) {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const count = viewport.getImageIds().length;
    const next = Math.min(Math.max(viewport.getCurrentImageIdIndex() + delta, 0), count - 1);
    viewport.setImageIdIndex(next);
    viewport.render();
  }

  function zoomBy(factor: number) {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const camera = viewport.getCamera();
    if (camera.parallelScale == null) return;
    viewport.setCamera({ parallelScale: camera.parallelScale / factor });
    viewport.render();
  }

  /** Back to the picture as it first opened: framing, window, middle slice. */
  function resetView() {
    const viewport = viewportRef.current;
    if (!viewport) return;
    viewport.resetCamera();
    viewport.resetProperties();
    setBrightness(0);
    setContrast(0);
    const base = baseVoiRef.current;
    if (base) viewport.setProperties({ voiRange: { ...base } });
    viewport.render();
  }

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
    // Visibility alone only drops the fill -- the per-segment outline is a
    // separate style flag, so unchecking the box left every disc still traced.
    segmentation.config.style.setStyle(
      {
        type: SegmentationRepresentations.Labelmap,
        viewportId,
        segmentationId,
      },
      { renderFill: segVisible, renderOutline: segVisible },
    );
  }, [segAvailable, segVisible, viewportId, segmentationId]);

  // Apply opacity whenever the slider changes.
  useEffect(() => {
    if (!segAvailable) return;
    segmentation.config.style.setStyle(
      {
        type: SegmentationRepresentations.Labelmap,
        viewportId,
        segmentationId,
      },
      // The outline has its own alpha; without it, sliding to 0 still leaves a
      // full-strength outline of every structure.
      { fillAlpha: segOpacity, outlineOpacity: segOpacity },
    );
  }, [segAvailable, segOpacity, viewportId, segmentationId]);

  return (
    <div>
      {error && <p style={{ color: "crimson" }}>Viewer error: {error}</p>}
      {segForeign && (
        <p
          style={{
            margin: 0,
            padding: "8px 12px",
            fontSize: "0.85rem",
            color: "#92400e",
            background: "#fffbeb",
            borderBottom: "1px solid #fde68a",
          }}
        >
          Segmentation belongs to the analysed series and is not shown here.
          Switch back to the series marked <strong>AI</strong> to see or edit it.
        </p>
      )}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-slate-200 bg-white px-3 py-2 text-xs text-slate-700">
        <span className="flex items-center gap-1">
          <button type="button" onClick={() => stepSlice(-1)} disabled={sliceIndex <= 0} className={VIEW_BTN} title={t("Previous slice")}>
            ◀
          </button>
          <span className="min-w-[72px] text-center tabular-nums">
            {t("Slice {i} / {n}", { i: sliceIndex + 1, n: sliceCount })}
          </span>
          <button type="button" onClick={() => stepSlice(1)} disabled={sliceIndex >= sliceCount - 1} className={VIEW_BTN} title={t("Next slice")}>
            ▶
          </button>
        </span>
        <span className="flex items-center gap-1">
          <button type="button" onClick={() => zoomBy(1.25)} className={VIEW_BTN} title={t("Zoom in")}>
            ＋
          </button>
          <button type="button" onClick={() => zoomBy(0.8)} className={VIEW_BTN} title={t("Zoom out")}>
            －
          </button>
        </span>
        <label className="flex items-center gap-1.5">
          ☀ {t("Brightness")}
          <input type="range" min={-100} max={100} step={5} value={brightness} onChange={(e) => setBrightness(Number(e.target.value))} className="w-24" />
        </label>
        <label className="flex items-center gap-1.5">
          ◐ {t("Contrast")}
          <input type="range" min={-100} max={100} step={5} value={contrast} onChange={(e) => setContrast(Number(e.target.value))} className="w-24" />
        </label>
        <button type="button" onClick={resetView} className={VIEW_BTN + " px-2.5"} title={t("Back to the original picture")}>
          ⟲ {t("Reset image")}
        </button>
      </div>
      {segAvailable && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "1rem",
            flexWrap: "wrap",
            whiteSpace: "nowrap",
            padding: "8px 12px",
            fontSize: "0.85rem",
            color: "#334155",
            background: "#f8fafc",
            borderBottom: "1px solid #e2e8f0",
          }}
        >
          <label>
            <input
              type="checkbox"
              checked={segVisible}
              onChange={(e) => setSegVisible(e.target.checked)}
            />{" "}
            {t("Segmentation")}
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            {t("Opacity")}
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
          {MASK_EDIT_ENABLED && !editDisabled && (
            <label>
              <input
                type="checkbox"
                data-testid="edit-mask-toggle"
                checked={editMode}
                onChange={(e) => onEditModeChange?.(e.target.checked)}
              />{" "}
              {t("Edit mask")}
            </label>
          )}
          {MASK_EDIT_ENABLED && editMode && !editDisabled && (
            <>
              <button
                type="button"
                data-testid="pick-tool"
                aria-pressed={pickArmed}
                onClick={() => {
                  setPickMissed(false);
                  setPicking((on) => !on);
                }}
                className={
                  "rounded-md border px-2 py-1 text-xs font-medium transition " +
                  (pickArmed
                    ? "border-teal-500 bg-teal-600 text-white"
                    : "border-slate-300 bg-white text-slate-700 hover:border-teal-400")
                }
              >
                ⌖ {t("Point & select")}
              </button>
              {onUndo && (
                <span
                  style={{ display: "inline-flex", gap: "0.25rem" }}
                  title={t("Undo the last edit (Ctrl+Z)")}
                >
                  <button
                    type="button"
                    data-testid="toolbar-undo"
                    onClick={onUndo}
                    disabled={!canUndo}
                    className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs font-medium text-slate-700 transition hover:border-teal-400 disabled:opacity-40"
                  >
                    ↶ {undoLabel ?? t("Undo")}
                  </button>
                  <button
                    type="button"
                    data-testid="toolbar-redo"
                    onClick={onRedo}
                    disabled={!canRedo}
                    title={t("Redo (Ctrl+Shift+Z)")}
                    className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs font-medium text-slate-700 transition hover:border-teal-400 disabled:opacity-40"
                  >
                    ↷
                  </button>
                </span>
              )}
              {onSave && (
                <button
                  type="button"
                  data-testid="toolbar-save"
                  onClick={onSave}
                  disabled={!canSave}
                  className="rounded-md bg-gradient-to-r from-teal-600 to-cyan-500 px-2.5 py-1 text-xs font-semibold text-white shadow-sm transition hover:brightness-110 disabled:opacity-40"
                >
                  {saveLabel ?? t("Save")}
                </button>
              )}
              <select
                value={editShape}
                data-testid="edit-tool"
                onChange={(e) => setEditShape(e.target.value as EditShape)}
              >
                <option value="brush">{t("Brush")}</option>
                <option value="circle">{t("Circle")}</option>
                <option value="rect">{t("Rectangle")}</option>
              </select>
              <select
                value={editAction}
                data-testid="edit-action"
                onChange={(e) => setEditAction(e.target.value as EditAction)}
              >
                <option value="paint">{t("Fill")}</option>
                <option value="erase">{t("Erase")}</option>
              </select>
              {editShape === "brush" && (
                <label
                  style={{ display: "flex", alignItems: "center", gap: "0.25rem" }}
                >
                  {t("Size")}
                  <input
                    type="range"
                    min={1}
                    max={20}
                    value={brushSize}
                    onChange={(e) => setBrushSize(Number(e.target.value))}
                  />
                </label>
              )}
              {legendEntries.length > 0 && (
                <LabelPicker
                  entries={legendEntries}
                  value={activeLabel}
                  onChange={(id) => onActiveLabelChange?.(id)}
                  disabled={editAction === "erase"}
                />
              )}
              {pickArmed ? (
                <span
                  data-testid="pick-structure-hint"
                  style={{ color: "#b45309", fontWeight: 500 }}
                >
                  {activeLabel == null
                    ? t("Click the structure on the image — nothing is selected yet.")
                    : t("Click the structure on the image.")}
                </span>
              ) : null}
              {pickArmed && (
                <span
                  data-testid="pick-hover"
                  className="flex items-center gap-1.5 text-slate-600"
                >
                  {hoverEntry ? (
                    <>
                      <Swatch color={hoverEntry.color} />
                      {structureName(hoverEntry.name)}
                    </>
                  ) : pickMissed ? (
                    t("Nothing there — that is background.")
                  ) : (
                    "—"
                  )}
                </span>
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
            // Pointing has no Cornerstone tool behind it, so it has no cursor
            // of its own either; say so explicitly.
            cursor: pickArmed ? "crosshair" : undefined,
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
