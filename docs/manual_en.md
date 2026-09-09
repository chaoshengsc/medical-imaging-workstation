# Medical Imaging Workstation — User Manual

> Development update (2026-09-07): this Markdown documents multi-series annotation, unified Undo, `.miwproj` persistence and 3-D registration. MR loading, editing and registration have synthetic-data evidence; real multi-series MRI acceptance is still pending. Automatic tumour localisation, segmentation and type prediction remain under model research. These instructions are not a release or a claim of complete acceptance; see the [implementation plan](annotation_tumor_plan.md). The frozen V1.0 PDF is unchanged.

**English** · [简体中文](manual_zh.md)

> This manual is written for software version V1.0. All screenshots are demonstrated using the **public dataset TotalSegmentator-CT-Lite (CC-BY-4.0)** — **public, de-identified human CT**. These are images of real patients: what the dataset removes is *identifiability*, not the clinical origin, so no identifiable personal health information (PHI) is present, but "not patient data" would be the wrong claim. The patient-information panel is explicitly labelled as public data.

> **Version correspondence.** According to the project filing records, the manual **PDF used for the software-copyright registration application is the V1.0 snapshot**; V1.0 is defined by that PDF, which this document does not retroactively amend. This Markdown source has continued to be maintained since V1.0 and now documents features that V1.0 did not yet contain (spacing resampling before inference, per-voxel confidence, the model card, the reconstruction lab's built-in phantom). The resulting differences reflect normal source evolution, not a correction to the submitted snapshot. **One difference is a wording correction rather than a feature**: the PDF's cover still describes the screenshot data as "not patient data", which this Markdown has since corrected to "public, de-identified human CT". The PDF is deliberately left untouched while the copyright holders have not received a formal acceptance notice from CPCC.

---

## 1. Software Overview

**Software name**: Medical Imaging Workstation Software
**Software version**: V1.0
**Introduction**: This software is a desktop CT medical imaging workstation built on PySide6 (Qt6), aimed at imaging teaching and research. It integrates three major parts — **clinical reading tools**, **AI multi-organ segmentation**, and a **CT tomographic-reconstruction teaching lab**. The software supports loading DICOM images, multi-planar reformation (MPR) reading, window width / window level adjustment, measurement and annotation, AI automatic organ segmentation and quantification, dual-series follow-up comparison, and a complete teaching demonstration from projection to reconstruction.
**Verified environment**: local macOS with Python 3.10; the data-independent suite had also passed historically on a GitHub Actions Ubuntu runner as of the snapshot below. Windows was not verified in that snapshot and no platform-compatibility claim is made for it. Dependencies include PySide6, pydicom, NumPy, SciPy, scikit-image, and ONNX Runtime.
**Development language**: Python.
**Software scale**: application code is split across UI mixins and Qt-free compute modules. A local run on 2026-08-30 recorded 1013 full-suite checks and 902 `SKIP_REAL_DATA=1` checks; these are local results, not fresh-clone, coverage, or remote-CI evidence.
**Positioning statement**: This software is a **teaching / research tool for imaging**, **not a certified medical device, and must not be used for clinical diagnosis**; AI segmentation and quantification results are automated inferences, for reference only.

---

## 2. Operating Environment and Launch

In a Python environment with the dependencies configured, run the following from the software root directory:

```
python main.py                          # empty start (no data loaded)
python main.py --data <DICOM directory path>    # load the specified DICOM directory on launch
```

After the software starts, it enters the main interface. By default it **loads no data**, waiting for the user to load data from the interface, as shown below.

![Empty-start interface](img/manual_startup_empty.png)

*Figure 2-1  The empty-start interface (English-UI example). The toolbar is on the left, the image view area in the centre, and the control panel on the right.*

---

## 3. Main Interface Layout

The main interface is divided into three columns:

1. **Left toolbar**: nine measurement / annotation tool buttons arranged top to bottom (probe & pan, distance caliper, freehand pen, rectangle capture, lasso, 3D tracking, segmentation brush, segmentation eraser, ROI densitometry). After a tool is selected with a click, mouse actions on the image correspond to that tool's function.
2. **Central image view area**: composed of 1–4 image views, supporting single-, dual-, and quad-view layouts. Each view has, along its top, dropdown / checkbox controls for plane selection (axial / coronal / sagittal), window-level presets and overlay display.
3. **Right control panel**: at the top are the "Load DICOM directory" and "Save annotation project" buttons; below them are two tabs, "Clinical reading / Reconstruction lab," which carry the clinical-reading controls and the reconstruction-lab controls respectively.

The top tabs switch between the two working modes, **Clinical reading** and **Reconstruction lab**.

---

## 4. Loading DICOM Data

Click **"Load DICOM directory"** and choose a directory of slices. The loader accepts **Classic single-frame CT Image Storage / MR Image Storage** and rejects Enhanced, multi-frame and other modalities. Series in the same Study remain separate; use the Study/series selectors to switch. Different Studies are never combined into one volume. The MR target is static structural imaging; dynamic, diffusion and multi-echo inputs remain unvalidated. For readable input, the software will:

- **Parallel disk reading**: read all DICOM files in the directory with multiple threads, speeding up loading of large series;
- **Multi-series handling**: multi-file input is grouped only when every slice has a `SeriesInstanceUID`; otherwise it fails closed rather than merging unknown series. The selected group is then filtered to the majority matrix shape;
- **Spatial sorting**: when every slice has finite, consistent `ImageOrientationPatient` and `ImagePositionPatient`, sort by the patient-space projection `dot(IPP, normal)`. If that geometry cannot be proved, fall back for the whole series to `InstanceNumber`, without claiming that this establishes anatomical order;
- **Intensity and unit proof**: every retained slice must have finite non-zero `RescaleSlope` plus finite `RescaleIntercept`, and must either declare `RescaleType=HU` or satisfy the classic CT standard guarantee (`ImageType` is `ORIGINAL`, not `LOCALIZER`, and not multi-energy). Otherwise the underlying volume stays raw and HU quantification, AI and HU follow-up remain disabled. A supported CT missing only its unit declaration can use all six window presets directly when its slices share a positive finite linear transform. The interface labels this as a display preview; no copied directory or DICOM editing is needed. Explicit non-HU units, inconsistent or missing transforms, localizers, multi-energy data and unsupported LUTs retain raw-value window sliders. Multi-energy CT remains unsupported even when some such images may intrinsically represent HU;
- **Separate source and spatial checks**: verifiable frame identities and decoded pixels determine whether annotations can safely persist. Patient geometry determines anatomical MPR and millimetre measurements; valid oblique acquisitions can use anatomical planes. A source-bound series without sufficient geometry permits original-slice editing without invented physical units. Editing is disabled when source identity cannot be established.
- **Separate CT and MR capabilities**: MR uses stored intensity values and WW/WL controls, never HU, the CT organ model, HU quantification, CT follow-up or image-based CT reconstruction. CT-specific consumers retain their full geometry/intensity requirements. The built-in phantom remains available independently for reconstruction teaching.

---

## 5. Clinical Reading

### 5.1 Slice Browsing and Navigation

The "Slice" slider on the right panel lets you browse layer by layer; you can also move the mouse into the image and use the scroll wheel to page through slices. The keyboard `↑ / ↓` and `PgUp / PgDn` keys also page through slices.

### 5.2 Window Width / Window Level Adjustment

The "Display control" area on the right provides two sliders, **WW (window width) / WL (window level)**, along with 6 clinical window-level preset buttons: **lung, mediastinum, bone, vessel, abdomen, brain**; there is also an **invert** checkbox. You can also hold the right mouse button and drag on the image to adjust window width / level in real time. The figure below shows the effect after switching to the **lung window**, displaying a chest axial slice.

![Clinical reading · lung window](img/manual_clinical_lung.png)

*Figure 5-1  Reading a chest axial slice under the lung window. The four corners overlay patient information (public data), window level, slice number, and anatomical orientation letters (A/P/R/L).*

### 5.3 Tri-planar MPR and Linked Cross-hairs

After enabling "MPR linkage," the quad-view layout can simultaneously display the three planes **axial, coronal, sagittal**. Moving the mouse in any view links the cross-hairs and slices of the other views to the same anatomical point; the anisotropic planes (coronal / sagittal) automatically correct their display aspect ratio according to anatomical proportions.

![Tri-planar MPR linkage](img/gui_mpr_triplanar.png)

*Figure 5-2  Tri-planar MPR + linked cross-hairs (lung window, AI lung-lobe colour overlay shown in the axial view).*

### 5.4 Layout Modes

The layout dropdown in the right "Display control" can switch between **single (1×1) / dual (1×2) / quad (2×2)** views.

### 5.5 Four-corner DICOM Information Overlay

When the "Information overlay" checkbox is enabled, the four corners of the image overlay patient information, window width / level, and slice number in PACS style, and anatomical orientation letters are marked at the image edges (A anterior / P posterior / R right / L left / S superior / I inferior).

### 5.6 Cine Playback and Keyboard Paging

The "Play" button starts Cine playback, automatically paging through slices continuously (bouncing back at the top / bottom, no wrap-around jump); the speed dropdown offers slow / medium / fast; clicking again pauses.

### 5.7 Slab Projection (MIP / MinIP / AIP)

The projection dropdown at the top of each view switches between four modes, with the spin box beside it setting the slab thickness in slices:

| Mode | Meaning | Typical use |
|---|---|---|
| **Slice** | Default, shows a single slice | Routine reading |
| **MIP** | Maximum intensity projection | **High-density** structures: lung nodules, vessels, bone |
| **MinIP** | Minimum intensity projection | **Low-density** structures: airways, emphysematous regions |
| **AIP** | Average intensity projection | Noise reduction, overall density distribution |

For canonical source acquisitions, projection runs along the current plane normal and is **supported on all three planes**. Oblique acquisitions currently allow single-plane viewing/editing with slab projection disabled. Selecting "Slice" disables the thickness box; in that state the displayed result is **pixel-for-pixel identical** to not using the projection feature at all.

> Why slab rather than whole-volume projection: clinical practice uses slab MIP (typically 5–20 mm). Collapsing the entire volume into one image superimposes unrelated anatomy and obscures the target instead of revealing it. Thickness is converted to millimetres per plane — axial uses slice thickness along z, coronal/sagittal use pixel spacing along the in-plane axis, since the two carry different physical scales.

---

## 6. Measurement and Annotation Tools

The nine tools in the left toolbar operate on the axial image after selection:

1. **Probe & pan**: click to read the HU value and coordinates at that point; drag to pan the view.
2. **Distance caliper**: drag out a straight line to measure the physical distance between two points (mm, converted by pixel spacing).
3. **Freehand pen**: draw annotation lines freely on the image.
4. **Rectangle capture**: box-select a rectangular ROI, compute the region's area and mean HU, and optionally export the cropped image and a CSV.
5. **Lasso**: draw a polygonal ROI to generate a segmentation mask.
6. **3D tracking**: box-select an ROI on one slice, extract its HU statistics, track HU-similar connected structures throughout the whole 3-D volume, and generate a 3-D mask.
7. **Segmentation brush**: paint on the current axial slice to add the strokes into the segmentation mask (an optional target organ can be chosen, and painted-in strokes count toward that organ's quantification), used to correct AI omissions.
8. **Segmentation eraser**: erase the mask where it was painted (can remove AI mis-segmentations).
9. **ROI densitometry**: drag out an elliptical ROI and read the interior mean ± SD / min-max HU / area; the ellipse can be dragged, resized, and deleted.

Rulers, freehand paths and ROIs retain their creation location. With patient-space geometry, other planes show the actual contour or intersection. The legacy global option repeats a 2-D reference on standard axial source slices; it does not define a 3-D lesion. Annotation creation, pixel editing, ROI movement/resizing, deletion and registration adoption share chronological `Ctrl+Z` Undo. The latest 20 operations persist with the project.

---

## 7. AI Multi-organ Segmentation

### 7.1 Automatic Inference

A CT series meeting the model's input requirements, without a recoverable working result, starts background sliding-window inference (`models/organs.onnx`, 25 thoracoabdominal organ classes including 5 lung lobes). MR never enters this model. Restored manual results and valid empty results do not trigger automatic recomputation. The existing engine can attempt connected-component lung segmentation if the model is missing or fails; this limited classical fallback does not identify tumour types. Failure is reported distinctly from no detection. Valid AI results enter read-only versions; a new version does not overwrite existing manual working results or clear edit history.

> **Spacing resampling before inference.** The model (nnU-Net v2) requires the volume to be resampled to its training voxel spacing (1.5 mm isotropic) first; the software does this automatically and says so in the status line. Skipping it has a measured cost: at twice the training spacing, mean Dice falls from 0.922 to 0.799, with small organs failing first. That measurement was made on the model's own RAS in-plane convention rather than through the product's DICOM (LPS) path, so it characterises the model rather than the product end to end. The step is not free either — mask boundaries are quantised to the 1.5 mm grid and appear stair-stepped when mapped back to a finer original resolution: **structural accuracy up, pixel-level boundary precision down**. Resampling is skipped when the series is already near 1.5 mm, or when the scan range is so large that resampling would exceed the memory limit.

### 7.2 Result Overlay and Legend

After inference completes, the segmentation result is overlaid on the image as a colour semi-transparent mask, **displayed on all three planes — axial, coronal and sagittal** (mask and image are taken as corresponding slices of the same 3-D array, so they align pixel for pixel); the legend on the right lists each detected organ and its colour, and **clicking a legend entry toggles that organ's visibility**.

![AI multi-organ segmentation overlay and organ quantification](img/gui_axial_segmentation.png)

*Figure 7-1  AI multi-organ segmentation result overlay (liver, spleen, kidney, stomach, lung lobes, etc.); the right legend includes each organ's volume / HU and a disclaimer.*

### 7.3 Cursor HUD

As the mouse moves over the image, the interface displays in real time the coordinates and HU value at the cursor, along with the name of the organ it lies in (if that voxel belongs to a segmented organ).

### 7.4 Organ Quantification Panel and CSV Export

The "Automated AI engine" area lists each detected organ's **volume (mL) and mean HU ± SD** (in descending order of volume). Clicking **"Export quantification CSV"** exports the quantification results to a CSV file (UTF-8-SIG encoding, so Excel displays Chinese correctly) carrying seven HU statistics per organ — mean, SD, median, 5th and 95th percentiles, minimum and maximum — alongside the volume, with the AI disclaimer embedded in the CSV.

> Why not the mean alone: a mean says nothing about how dispersed the density is inside an organ, and that dispersion is what tells you whether the segmentation has absorbed neighbouring tissue — and is a precondition for any statistical comparison. The 5th/95th percentiles are more robust to single-voxel noise than the extremes.

The panel also reports each organ's **confidence** (the model's softmax max-class probability) together with its **5th percentile**: the mean is pulled up by the large confident interior of an organ, whereas segmentation errors concentrate at boundaries, so the low percentile is the more revealing number; entries below 0.9 are flagged in orange. If an organ has been edited with the brush or 3D tracking, a **model-decided share** is shown as well — hand-edited voxels are excluded from the confidence statistics, because their stored value is the model's judgement about *the label that was there before the edit*, which says nothing about the current one. The manual tracking layer reports no confidence at all, since the model never judged it.

The **"Model card: provenance & limits"** button sets out how the label mapping was recovered by measurement, why the model's identity as a particular upstream release remains an inference rather than a proof, how far it has been validated, and what its known limits are. Every number on the card is read live from the experiment outputs under `experiments/results/`, so re-running an experiment updates the card.

### 7.5 3D Surface Reconstruction

Click **"3D Surface Preview"** and the software reconstructs a 3-D surface for **the organ currently selected as the brush target**, opening a dialog with a **drag-to-rotate** 3-D view together with **surface area, volume, sphericity and face count**. From there the mesh can be **exported as STL** (ASCII, millimetre units, ready for 3D printing or external software).

**Interaction**: press and drag on the image to rotate — horizontal motion changes azimuth, vertical motion changes elevation (0.5°/px); the six buttons on the right (Ant / Post / Left / Right / Sup / Oblique) jump to standard views; the current angles are shown live below the image. Elevation is clamped to ±89° to avoid gimbal lock, where the view direction aligns with the rotation axis, azimuth loses meaning and the image flips abruptly.

The pipeline is **isosurface extraction (marching cubes) → Taubin smoothing → vertex-clustering decimation**, matching the surface-model workflow used by 3D Slicer. Rendering is implemented in pure numpy (orthographic projection + Lambert shading + painter's-algorithm depth sorting), with no dependency on OpenGL or VTK, so no GPU is required. The trade-off is no perspective and no shadows.

> **How the rotation stays responsive**: a full-mesh frame takes ≈ 114 ms (measured, 360 px view, 4,615 faces) — driving the mouse with that is visibly choppy. The dialog therefore **drops quality while dragging and restores it on release**: during a drag it renders a further-decimated mesh (measured on a real organ: 6,798 → 1,984 faces, ≈ 48 ms/frame), and the instant the button is released it repaints one frame from the full mesh — so **what you see at rest is always full precision**. The coarse mesh affects the drag preview only; **shape features and STL export always use the full mesh** (the coarse mesh is 1.6% off in volume, which would corrupt quantification).

> **How spacing resampling propagates into shape features (measured)**: inference now resamples the volume to the model's training spacing (1.5 mm), so mask boundaries are quantised to that grid. On an analytic sphere (R = 20 mm, native 0.713 mm grid, 10 smoothing iterations) this moves the surface-area error from +0.26% to **+1.95%**, the volume error from −0.18% to **−0.97%**, and sphericity from 0.9962 to 0.9745. Taubin smoothing absorbs most of the staircase so the magnitude stays small, but anyone using shape features for quantitative comparison should know the figure includes this term.

> **Why smoothing matters**: marching cubes alone leaves a voxel staircase, which inflates surface area. Measured on an analytic sphere (R = 20, spacing 1 mm): without smoothing the surface area is **+9.3%** high and sphericity is 0.915; after 10 Taubin iterations these become **+1.2%** and 0.988, while **volume shifts by only +0.08%**. Taubin alternates a positive and a negative pass so the shrinkage cancels — plain Laplacian smoothing would steadily shrink the mesh and corrupt the volume measurement. Decimation (roughly halving the face count by default) halves render time at a volume error on the order of 0.1%.

### 7.6 Segmentation Editing

Select an editable working layer before using the segmentation brush or eraser. Organ and lesion layers are independent and can overlap. "New lesion layer" creates a separate lesion identifier; its type stays unknown without a type-prediction model.

To annotate the same lesion in another series of this Study, select its working lesion layer in the reference series, switch to the target series, select the reference series, and click "Link reference lesion". This creates an empty layer with the same identifier; draw its extent independently in the target series. Statistics remain per series. Linking is undoable and persists in the project. The control is disabled when correspondence is unavailable, the reference is an organ layer, or that lesion already has a layer in the target series.

Set the brush radius to its minimum, `1 voxel`, to add or remove one source voxel per click. Zooming, panning or changing anatomical planes does not turn this into a screen-pixel edit. Press–drag–release forms one operation; `Ctrl+Z` reverses it. Erasing changes labels, while Undo restores a previous operation. Changing tool, slice or series cancels an unfinished stroke.

Select an original AI version for read-only comparison. "Use this AI version as working result" is undoable. Manual edits do not create model confidence or rerun classification. "Clear current plane" and "Clear Mask & Annotations" are separate: the latter clears all slices of the active working layer and the current series' ordinary annotations, with the scope stated in its confirmation. Both are undoable. Reset restores display/layout while retaining annotations and history.

---

## 8. Dual-series Follow-up Comparison

Click **"Load comparison series"** and select the prior DICOM directory. Dual-view comparison is entered only when both series satisfy HU calibration, canonical orientation, valid in-plane spacing, and uniform projected-z geometry. Slice correspondence uses each series' `dot(IPP, normal)` patient-space positions; missing or irregular geometry is rejected explicitly rather than presented as anatomical correspondence through index-ratio fallback. When de-identification is enabled, the prior examination date in the comparison title is hidden.

### 8.1 Difference quantification

After registration, the V2 title bar reports the HU difference for the current slice in real time: **Δ mean** (current − prior; positive means denser now), **mean absolute difference**, and **RMSE**. Switching to the quad-view layout shows a **difference map** in V3: warm colours where density has increased, cool where it has decreased, transparent where there is no change.

If matrix sizes or row/column pixel spacing differ, or the current slice is outside the prior series' z coverage, the software marks the pair as incomparable, skips registration and difference quantification, and clears any previous difference map. Both images remain available side by side; an out-of-coverage prior image is explicitly labelled as the nearest endpoint, not a corresponding slice.

### 8.2 In-plane rigid registration

The **"Register"** checkbox in the top toolbar (**enabled only in comparison mode**; disabled until a prior series is loaded) rigidly aligns the prior slice to the current one before comparing: translation is estimated by **phase correlation**, then rotation is searched within ±6° in 0.5° steps, keeping whichever maximises normalised cross-correlation (NCC). The title bar reports the estimated angle, translation and the NCC before/after.

This angle search applies only to square pixels. With matching spacing but non-square pixels, only translation is estimated and the title states that limitation: rotation in pixel-index coordinates is not directly a rigid rotation in physical space.

- **Safety valve**: if NCC does not improve (mismatched levels, anatomy changed too much), the transform is **rejected** and the title says so — better no registration than an alignment that makes things worse.
- **Measured effect**: for a prior series shifted by (12, −9), mean absolute difference drops from **321 HU to 13 HU**, NCC 0.85 → 0.99.

> **Important limitation**: rigid registration corrects **posture only** (translation + rotation); there is **no deformable registration**, so respiratory organ deformation is not corrected. Choosing rigid over deformable is deliberate — deformable registration absorbs breathing motion but also warps away **genuine lesion change**, which defeats the purpose of a follow-up comparison. The reported difference therefore **remains a qualitative indicator, not a clinical measurement of lesion change**. In addition, the prior series is not run through AI inference, so **organ-level volume change is not provided**.

---

## 9. Reconstruction Lab (CT Tomographic-reconstruction Teaching)

Click the top tab to switch to **"Reconstruction lab."** This module takes the current slice as its subject and fully demonstrates the process from X-ray projection to image reconstruction. Within it, the forward Radon projection and the analytic inverses (BP / FBP) are built on scikit-image's `radon` / `iradon`; the five inverse-solver algorithms DFR, DMR, ART, SIRT and ASD-POCS are implemented as self-contained numerical code in this project.

![Reconstruction lab](img/manual_recon_lab.png)

*Figure 9-1  The reconstruction lab quad view: V1 the real slice, V2 the projection sinogram, V3 the unfiltered back-projection (blurry), V4 the filtered back-projection FBP (sharp); on the right are the projection / algorithm controls and performance monitoring.*

### 9.1 Built-in Phantom (No Data Required)

Clicking **"Load Shepp-Logan phantom"** makes the entire reconstruction lab usable with no DICOM loaded at all. The phantom is generated analytically from ten superposed ellipses (Toft's revised parameters, the same convention as Study I), so it can be produced at any resolution without interpolation blur.

Its decisive advantage over a real slice is that **the ground truth is known**: the V3 error map then measures the distance between the reconstruction and the truth. For a real slice the "ground truth" is only the original image, which already carries noise and reconstruction artefacts of its own, so the error map measures the distance to *that* — not to the truth. Clicking again unloads the phantom and clears the sinogram and reconstructions derived from it, so a phantom sinogram is never left paired with a real-data reference image.

### 9.1.1 Projection Generation (Radon Transform)

In the "X-ray projection generation" area on the right, select the **angular range (60° / 120° / 180° / 360°)** and the **sampling density (standard 1× / high 2× / ultra 4×)**, then click **"Emit rays to generate sinogram"** to perform the Radon transform on the current slice and generate the projection sinogram, shown in V2.

### 9.2 Analytic Reconstruction

The "Image reconstruction algorithms" area provides:

- **Direct Fourier reconstruction (DFR)**: reconstructs directly from the sinogram based on the Fourier central-slice theorem;
- **Back-projection (BP, unfiltered)**: pure back-projection, with a blurry result (star-shaped artefacts), shown in V3 for comparison;
- **Filtered back-projection (FBP)**: with a choice of 5 filters (Ram-Lak / Shepp-Logan / Cosine / Hamming / Hann), the result shown in V4.

### 9.3 Matrix / Iterative Reconstruction

In the "Matrix Recon & Iterative" area, select the **image size (16/32/64)**, **iterative method (ART / SIRT / ASD-POCS)**, and **iteration count**; it provides:

- **Direct matrix reconstruction (DMR)**: solves the projection system of equations by least squares;
- **ART / SIRT / ASD-POCS iterative reconstruction**: algebraic and TV-regularised iterative reconstruction, with an error map and RMSE.

### 9.4 Deep-Learning Reconstruction (CNN post-processing)

Click **"DL Recon (CNN post-processing)"** to remove sparse-view FBP streak artefacts with a self-implemented residual U-Net. **V3 shows the network's input (ramp-FBP) and V4 its output**, so what the network actually changed can be compared directly.

Method and quantitative results are in the [experiments guide](../experiments/README.md) and Study III of the [technical report](technical_report.md): on a random phantom family, RMSE is 3–6× lower than the best linear filter and lesion-contrast retention rises from 0.87 to 0.957–0.996. Across **60 noise-free synthetic paired phantoms**, the false-structure rate is **1.67%** at the 20%-of-lesion threshold and **0%** at 30% and 50%. Photon noise was not applied, so 1.67% is neither an upper nor a lower bound for low-dose CT; both direction and magnitude are unmeasured, and low SNR is not claimed as the dominant driver.

> **Three limitations are stated in the UI itself, not just in the docs:**
> - **The model was trained at 20 views.** When the current view count differs, the V4 title is tagged "⚠ view mismatch" — results degrade at other view counts, and the software does not pretend otherwise.
> - **The input is forced to Ram-Lak (ramp) FBP**, regardless of the filter dropdown above. Smoothing filters (Hann and friends) have already discarded the high frequencies — and the detail with them — at the filtering stage, and the network cannot recover what is gone; ramp keeps the information but leaves streaks, and streaks are what can be learned.
> - **With the model or onnxruntime missing, the button stays disabled** and the tooltip explains why and how to obtain it. The repository ships only the 20 KB `.onnx` graph; the 7.7 MB weights (`.onnx.data`) must be trained and exported locally — the same convention as `organs.onnx`, and the two files must sit in the same directory.

### 9.5 Performance Monitoring

The "Algorithm performance monitoring" area displays in real time the running time of each reconstruction algorithm (as in Figure 9-1, "FBP (ram-lak) time: 254.9 ms").

---

## 10. Compliance and De-identification

- **De-identification switch**: after "De-ID" is enabled, on-screen identity is shown as `ANON`; explicit export filenames use a random `ANON-…` alias generated for the current load and add a suffix on collision, so repeated exports do not silently overwrite one another. This is not a DICOM anonymizer: it does not rewrite source DICOM tags or remove burned-in pixel text. Internal .miwproj projects and legacy mask caches retain patient/series identifiers and a geometry fingerprint for matching, and the UI warns again when saving them.
- **Project-state persistence**: an AI-pending placeholder does not count as a completed AI result. Fully erased or explicitly cleared working layers persist as empty; original AI layers and old caches cannot fill them back in on reopening. The latest 20 Undo operations survive reopening.
- **AI disclaimer**: the AI panel permanently displays a disclaimer, and the exported quantification CSV also embeds that disclaimer.

---

## 11. Bilingual (Chinese / English) Toggle

The language button in the top-right corner of the interface toggles between **Chinese / English** with one click, and all persistent widget text (tools, buttons, panel titles, dropdown items, hover tooltips, status text, etc.) is re-translated accordingly. The figure below shows the English-UI example.

![English interface](img/manual_english_ui.png)

*Figure 11-1  The English interface (mediastinum window, abdominal axial slice).*

---

## 12. Annotation Project Persistence

### 12.1 Save All Series and Annotated Slices

"Save Project" saves all series retained in the current Study, every annotated slice and the latest 20 Undo operations. The default directory is `Annotation_Projects/` under the application directory. "Choose Save Directory" changes it and remembers the choice. The status reports pending, saving, the last successful save time or failure; its tooltip shows the full path and formats. "Open Save Directory" locates the file.

Completed changes save automatically after 2 seconds of inactivity, with a save scheduled every 30 seconds during continuous editing. AI and registration versions also trigger saving. An unfinished stroke is excluded. Edits made during saving remain pending until the newer revision is written. Closing or changing Study handles the latest save first; failures offer retry, another directory, staying in the project or explicitly discarding changes.

The `.miwproj` file is one ZIP package. `manifest.json` records source identities, layers, timestamps and registration; per-series NPZ members hold labels and available confidence; `history.json` and compressed differences hold Undo. `summary.csv` records lesion identifiers, source-grid extent, voxel count, type/unknown and revision status. Volume/HU are recorded only with proven geometry/units; unavailable values are not reported as zero. The package commits as one unit, leaving the previous complete file intact if saving fails.

### 12.2 Open, Reconnect and Migrate

Loading the same Study first attempts its matching project. "Open Project" selects an explicit `.miwproj`. Source DICOM images are not bundled: retain them or reconnect their directory. Matching checks Study/Series/SOP identities, decoded pixels and spatial bindings, not just patient name or array shape.

Loading only one series preserves the other series' offline annotations, results, transforms and history on resave. Load the missing source directory to reconnect and edit it. If the top Undo operation needs an offline source, Undo stops and explains the missing input instead of skipping back to an earlier operation.

Legacy JSON/NPZ in `Exported_Lesions/` are read for migration only; new saves use the new project format. A legacy cache is a historical working result, without invented original AI, confidence or pre-migration Undo. A damaged project does not silently fall back to older caches. If only history is damaged while the final state is intact, an explicit recovery option creates a separate copy without the damaged history and preserves the original file. Damaged final layers or source metadata cannot use that recovery path.

### 12.3 Correspondence Within an MRI Study

"Keep patient location across series" attempts to navigate to the corresponding position when switching series. Shared FrameOfReference and overlapping geometry provide metadata location only, labelled as motion-unverified. An unavailable or out-of-coverage position is not clamped to a target boundary.

Choose a reference series and click "3-D rigid registration" to calculate a candidate. Browse the Axial, Coronal and Sagittal sliders in the review dialog, comparing the current, aligned reference and overlay images. "Keep candidate" does not adopt it. "Reviewed all planes — adopt" records visual review and creates an undoable adoption. A better metric does not prove anatomical alignment; visual review is distinct from landmark or clinical validation.

"Show reference annotations (read-only)" displays transformed masks and patient-space annotations without overwriting either source layer. Two-dimensional global references are not projected to another series. Real multi-series MRI acceptance remains pending; missing geometry, no overlap or failed registration must not force annotations onto another image.

---

*(End of manual)*
