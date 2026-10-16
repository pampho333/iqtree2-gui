# IQ-TREE 2 GUI v0.1.5

An unofficial desktop GUI for IQ-TREE 2, supporting Windows and Windows Subsystem for Linux (WSL2).

## Highlights
- Choose text, background, and accent colors with a color picker or HEX values; preferences persist across sessions.
- Blinking activity indicator while an analysis is running.
- Check-mark style checkboxes and improved font sizing.
- Search and select one or multiple outgroup taxa directly from an alignment (FASTA, PHYLIP, or NEXUS).
- Configure ModelFinder, partition models, UFBoot, SH-aLRT, BNNI, CPU threads, and other IQ-TREE options without typing commands.
- View live logs, open results, preview Newick trees, and export SVG graphics.

## Downloads
- **IQTree2_GUI_Windows_v0.1.5.zip**: standalone Windows GUI executable and documentation. No separate Python installation required.
- **IQTree2_GUI_v0.1.5_Source.zip**: the Python source, sample data, tests, and build scripts.
- GitHub also supplies source archives automatically.

## Requirements and limitations
**IQ-TREE 2 itself is not bundled.** Download the appropriate IQ-TREE 2 binary separately and select it within the GUI, or run an existing IQ-TREE 2 installation through WSL2.

Windows EXE packaging and automated unit tests run on GitHub Actions. Full IQ-TREE analysis with real biological data and environment-specific WSL interoperability are not validated by the build workflow.

Project source: https://github.com/pampho333/iqtree2-gui
