import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  RenderingEngine,
  Enums,
  imageLoader,
  type Types,
} from "@cornerstonejs/core";
import {
  ToolGroupManager,
  addTool,
  StackScrollTool,
  ZoomTool,
  PanTool,
  WindowLevelTool,
  segmentation,
  Enums as csToolsEnums,
} from "@cornerstonejs/tools";
import { createNiftiImageIdsAndCacheMetadata } from "@cornerstonejs/nifti-volume-loader";
import { ensureCornerstoneInitialized } from "../../lib/cornerstone";

const { ViewportType } = Enums;
const { MouseBindings, SegmentationRepresentations } = csToolsEnums;

interface Props {
  studyId: string;
  apiBaseUrl: string;
  /** Optional overlay pinned inside the image box (e.g. a PACS-style header). */
  overlay?: ReactNode;
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
}: Props) {
  const elementRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [segAvailable, setSegAvailable] = useState(false);
  const [segVisible, setSegVisible] = useState(true);
  const [segOpacity, setSegOpacity] = useState(0.5);

  const viewportId = `vp-${studyId}`;
  const segmentationId = `seg-${studyId}`;

  useEffect(() => {
    let cancelled = false;
    let engine: RenderingEngine | undefined;

    const renderingEngineId = `engine-${studyId}`;
    const toolGroupId = `tg-${studyId}`;

    (async () => {
      await ensureCornerstoneInitialized();

      const url = `${apiBaseUrl}/studies/${studyId}/display.nii.gz`;
      const imageIds = await createNiftiImageIdsAndCacheMetadata({ url });
      if (cancelled || !elementRef.current) return;

      engine = new RenderingEngine(renderingEngineId);
      engine.enableElement({
        viewportId,
        element: elementRef.current,
        type: ViewportType.STACK,
      });

      [StackScrollTool, ZoomTool, PanTool, WindowLevelTool].forEach(addTool);
      const toolGroup =
        ToolGroupManager.getToolGroup(toolGroupId) ??
        ToolGroupManager.createToolGroup(toolGroupId);
      if (!toolGroup) return;

      toolGroup.addTool(WindowLevelTool.toolName);
      toolGroup.addTool(PanTool.toolName);
      toolGroup.addTool(ZoomTool.toolName);
      toolGroup.addTool(StackScrollTool.toolName);
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
      segmentation.removeSegmentation(segmentationId);
      ToolGroupManager.destroyToolGroup(toolGroupId);
      engine?.destroy();
    };
  }, [studyId, apiBaseUrl, viewportId, segmentationId]);

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
        </div>
      )}
      <div style={{ position: "relative" }}>
        <div
          ref={elementRef}
          onContextMenu={(e) => e.preventDefault()}
          style={{
            position: "relative",
            width: "100%",
            height: "600px",
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
