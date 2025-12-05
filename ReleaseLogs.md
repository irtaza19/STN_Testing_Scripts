# Releaselogs

## v1.0.0
### Added
- First release of the test scripts.

### Fixed


### Important Notes
- Run these commands twice for stable results: **AT@2, STVCALSTAT, STSDI, STDI**
- **ATRTR** gives a different result every time.
- **STVR** gives almost identical values with only small fractional differences.
- **STVRX**: ADC is set to 12-bit, but dsPIC ADC gives a smaller value compared to STN.
- **STPIR, STGPIRH, STGPOR** behave differently because pin counts differ between STN and dsPIC.
- **ATZ** works fine; differences come from **STP** because dsPIC does not support all protocols.
- **STDICPO**: Power count will always be different across chips.
- **STPC / ATCS**: Error count changes every time.

### Included Files
- **STN_Scripts/** – All test scripts  
- **Testing_logs/** – Logs comparing STN and dsPIC  
- **SNAPS/** – Test snapshots  
- **Extras/** – Extra test scripts and values  

---
