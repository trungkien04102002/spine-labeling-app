import { useEffect, useRef, useState } from "react";
import { RenderingEngine, Enums, type Types } from "@cornerstonejs/core";
import {
  ToolGroupManager,
  addTool,
  StackScrollTool,
  ZoomTool,
  PanTool,
  WindowLevelTool,
  Enums as csToolsEnums,
} from "@cornerstonejs/tools";
import { createNiftiImageIdsAndCacheMetadata } from "@cornerstonejs/nifti-volume-loader";
import { ensureCornerstoneInitialized } from "../../lib/cornerstone";

const { ViewportType } = Enums;
const { MouseBindings } = csToolsEnums;

interface Props {
  studyId: string;
  apiBaseUrl: string;
}

/**
 * Renders a study's NIfTI as a 2D stack viewport (one image per slice) with
 * wheel slice scroll, left-drag window/level, middle-drag pan, right-drag zoom.
 * A stack viewport auto-fits each slice to the canvas — the right fit for
 * reviewing sagittal MRI.
 */
export default function CornerstoneViewport({ studyId, apiBaseUrl }: Props) {
  const elementRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let engine: RenderingEngine | undefined;

    const renderingEngineId = `engine-${studyId}`;
    const viewportId = `vp-${studyId}`;
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
      ToolGroupManager.destroyToolGroup(toolGroupId);
      engine?.destroy();
    };
  }, [studyId, apiBaseUrl]);

  return (
    <div>
      {error && <p style={{ color: "crimson" }}>Viewer error: {error}</p>}
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
    </div>
  );
}
