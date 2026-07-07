import { init as coreInit, imageLoader } from "@cornerstonejs/core";
import { init as toolsInit } from "@cornerstonejs/tools";
import {
  init as niftiLoaderInit,
  cornerstoneNiftiImageLoader,
} from "@cornerstonejs/nifti-volume-loader";

let initPromise: Promise<void> | null = null;

/** Initialize Cornerstone3D core, tools, and the NIfTI loader exactly once. */
export function ensureCornerstoneInitialized(): Promise<void> {
  if (!initPromise) {
    initPromise = (async () => {
      await coreInit();
      await toolsInit();
      niftiLoaderInit();
      // Register the per-image NIfTI loader so 'nifti:' imageIds resolve.
      imageLoader.registerImageLoader("nifti", cornerstoneNiftiImageLoader);
    })();
  }
  return initPromise;
}
