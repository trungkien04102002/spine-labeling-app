import { useEffect, useRef, useState } from "react";
import {
  RenderingEngine,
  Enums,
  volumeLoader,
  setVolumesForViewports,
} from "@cornerstonejs/core";
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

const { ViewportType, OrientationAxis } = Enums;
const { MouseBindings } = csToolsEnums;

interface Props {
  studyId: string;
  apiBaseUrl: string;
}

/**
 * Renders a study's NIfTI as a sagittal volume viewport with slice scroll
 * (wheel), window/level (left drag), pan (middle drag) and zoom (right drag).
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

      const url = `${apiBaseUrl}/studies/${studyId}/display`;
      const imageIds = await createNiftiImageIdsAndCacheMetadata({ url });
      if (cancelled || !elementRef.current) return;

      const volumeId = `nifti-vol-${studyId}`;
      const volume = await volumeLoader.createAndCacheVolume(volumeId, {
        imageIds,
      });

      engine = new RenderingEngine(renderingEngineId);
      engine.enableElement({
        viewportId,
        element: elementRef.current,
        type: ViewportType.ORTHOGRAPHIC,
        defaultOptions: { orientation: OrientationAxis.SAGITTAL },
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

      await setVolumesForViewports(engine, [{ volumeId }], [viewportId]);
      volume.load();
      engine.renderViewports([viewportId]);
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
        style={{ width: "100%", height: "600px", background: "black" }}
      />
    </div>
  );
}
