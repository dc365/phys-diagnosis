# NAFP integration status

The new weather-system feature algorithms are now connected through the NAFP situation cache path.

Integration files:

- weather_diag/diagnosis/nafp_situation_integrated.py
- weather_diag/diagnosis/nafp_cache.py

Connected objects:

1. shear_line and front_with_shear
2. low_level_convergence_axis
3. upper_divergence_axis
4. cold_vortex and mid_level_vortex
5. upper_jet
6. upper_jet_exit_region
7. pv_anomaly
8. surface_front_candidate and dryline_candidate

Also updated:

- display ranking and primary flags
- evidence-chain supporting systems
- risk diagnosis supporting systems
- support weights for the new weather systems

Follow-up work:

- add the new entries to the algorithm governance threshold matrix
- group MapLibre layers into default systems, supporting diagnostics, risk layers and debug layers
- calibrate thresholds with test_datas/NAFP_ECTHIN_NC and manually checked weather cases
