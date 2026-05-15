# large-font-printer
# Large Character Pagination Printing System – Complete Project Description
This is a **GUI-based professional tool** that supports ultra-large font automatic pagination, multiple fill styles, custom color configuration, and PDF export for single Chinese characters and symbols.

## Project Core Positioning
A cross-platform (Windows / Linux / macOS) **ultra-large character automatic pagination printing utility**.
- Input: Single Chinese character, letter or symbol
- Output: Multi-page standard PDF file
- Feature: Automatically split oversized characters into standard paper sizes (A4/A3/A0 etc.) for easy printing and splicing into giant characters.

It solves the common limitation of ordinary Word/printing software: inability to scale a single character to an extremely large size or automatically split it across multiple pages. This tool completes the whole process fully automatically.

## Core Features
### 1. Ultra-Large Character Automatic Pagination Printing
- Unlimited scaling of a single character
- Automatically split graphics according to standard paper sizes: A4 / A3 / A2 / A1 / A0 / Letter
- Ready for direct printing; pages can be assembled into one giant character

### 2. Eight Built-in Fill Styles
- Solid Color Fill
- Horizontal Gradient
- Vertical Gradient
- Radial Gradient
- Crosshatch Pattern
- Dot Pattern
- Parallel Line Pattern
- Grid Pattern

### 3. Full Font Compatibility
- Supports **TTF / OTF** font formats
- Compatible with Chinese, English, numbers and symbols

### 4. Custom Visual Styling
- Adjustable scaling factor (1 ~ 20×)
- Custom primary and secondary gradient colors
- Adjustable pattern density
- Custom output PDF file path and name

### 5. Real-time Preview System
- Grid thumbnail preview for page layout
- Detailed single-page preview
- Click thumbnails to switch between pages instantly

### 6. High-Definition Vector PDF Export
- Vector graphics, **lossless at any zoom level**
- Directly printable
- Importable into AI / PS / CAD and other design software

## Technical Architecture
### Development Language
Python 3.x

### Core Dependencies
| Library | Function |
|---------|----------|
| fontTools | Parse TTF/OTF fonts and extract glyph vector contours |
| shapely | 2D geometry computation, polygon processing, automatic page splitting |
| reportlab | Generate high-quality vector PDF with gradient & pattern fills |
| tkinter | Graphical user interface (GUI) |
| numpy | Bezier curve calculation and coordinate transformation |
| PIL | Image rendering for GUI preview |

### Overall Workflow
```
Font Loading → Glyph Contour Extraction → Coordinate Transformation
→ Geometry Construction → Automatic Pagination → PDF Rendering → GUI Preview
```

## Module Detailed Explanation
### 1. Font Parsing & Contour Extraction Module
- Custom `ContourPen` to extract vector glyph contours
- Accurately parse **straight lines and cubic Bezier curves** for smooth character edges
- Automatically recognize **outer contours and inner holes** (e.g., 回, 国, O, 8, B)

### 2. Geometry Processing Module
- Construct standard polygons with inner holes
- Auto-repair topological geometry errors
- Precisely split oversized graphics by standard paper size
- Coordinate transformation to ensure correct printing orientation

### 3. PDF Generation Module
- Export standard vector PDF files
- Support 8 fill styles
- Linear gradient / radial gradient rendering
- Pattern filling: grid, dots, lines, crosshatch
- Automatic multi-page layout generation

### 4. GUI Interface Module
- Font file selection
- Single character input
- Scale ratio & paper size configuration
- Color and fill style setup
- Pagination thumbnail layout preview
- Detailed single-page preview
- One-click PDF generation
- Real-time status prompt bar

## GUI Interface Instruction
### Left Control Panel
1. **Font File**: Select local TTF/OTF font
2. **Input Character**: Only one single character allowed
3. **Scale Factor**: Adjust overall character size
4. **Page Size**: A4 / A3 / A2 / A1 / A0 / Letter
5. **Fill Style**: 8 visual styles to choose from
6. **Primary / Secondary Color**: For solid color and gradient rendering
7. **Pattern Density**: Adjust density of line / dot / grid patterns
8. **Output File**: Set save path for generated PDF
9. **Generate PDF**: One-click export and rendering

### Right Preview Panel
1. **Page Layout Preview**
   Grid layout showing all split pages; red border marks the currently selected page
2. **Detailed Preview**
   High-definition display of the selected single page

## How to Use
### 1. Install Dependencies
```bash
pip install numpy fonttools shapely reportlab pillow
```

### 2. Prepare Font File
Place any `.ttf` / `.otf` font file in the program directory.

### 3. Run the Program
```bash
python big_font_print.py
```

### 4. Operation Steps
1. Select font file
2. Input **one single character**
3. Adjust scaling factor
4. Choose paper size
5. Select fill style and colors
6. Click **Generate PDF**
7. Print the PDF directly and splice pages into a giant character

## Application Scenarios
1. School / company slogan large characters
2. Poster, exhibition board and banner production
3. Super-large teaching characters for education
4. Art creation and paper-cut pattern design
5. Vector text for CAD / engraving machines
6. 3D printing outline generation
7. Seal and logo pattern design

## Project Highlights
1. Fully automatic pagination without manual cutting
2. Vector high definition, lossless at any magnification
3. Perfect support for characters with inner hollow holes
4. 8 professional fill styles for visual customization
5. Real-time WYSIWYG preview
6. Cross-platform support: Windows / macOS / Linux
7. Fully local offline operation, no file upload required
8. Highly extensible code structure for further function expansion

## Advanced Technical Features
- Complete TrueType glyph contour parsing implementation
- Robust polygon handling with nested hole structures
- Geometry-based precise automatic pagination algorithm
- Professional PDF rendering with gradient and pattern fills
- Dual preview system: grid thumbnail + detailed view
- Comprehensive exception handling and automatic geometry repair

## Summary
This is a **fully functional, user-friendly, professional-grade ultra-large character printing system**.
It is not only a ready-to-use tool, but also a complete technical solution covering **font parsing → geometry processing → vector rendering → pagination printing**.

**One-sentence Overview**:
Input one character → Auto scale to giant size → Auto split into standard pages → Export printable multi-page PDF → Assemble into oversized character by printing and splicing.
