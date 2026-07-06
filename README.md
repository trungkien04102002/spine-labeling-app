# spine-labeling-app

A local web tool for doctors to open a lumbar-spine MRI, review AI-generated overlays (anatomy segmentation + abnormality grading), correct them, and export the results. MySQL stores metadata/annotations only; MRI volumes and masks live on the filesystem.

Backend: `cd backend && uvicorn app.main:app --reload`
