"""
Curated manual resolution of the 8 previously-flagged products.
Each entry: (model_code, capacity, variant, method)
  method: 'source_explicit'          = capacity stated next to / for this model in the source
          'model_code_convention'    = capacity assigned via the OH/OL/RB-LI code convention,
                                        cross-checked against the source's capacity list
Derived by reading the raw datasheet text for each product; see message for provenance.
"""
RESOLVED = {
 "PROD-003": [  # T-4001 1-10k With Built-in Batteries: two model variants per capacity
   ("OH1001T10207S","1KVA/1KW","",  "model_code_convention"),
   ("OH1001T10209S","1KVA/1KW","",  "model_code_convention"),
   ("OH1002T10407S","2KVA/2KW","",  "model_code_convention"),
   ("OH1002T10409S","2KVA/2KW","",  "model_code_convention"),
   ("OH1003T10607S","3KVA/3KW","",  "model_code_convention"),
   ("OH1003T10609S","3KVA/3KW","",  "model_code_convention"),
   ("OH1006T11607S","6KVA/6KW","",  "model_code_convention"),
   ("OH1006T11609S","6KVA/6KW","",  "model_code_convention"),
   ("OH1010T11607S","10KVA/10KW","","model_code_convention"),
   ("OH1010T11609S","10KVA/10KW","","model_code_convention"),
 ],
 "PROD-004": [  # T-4001 1-10k Long Back-up: 6k & 10k each have two variants
   ("OH1001T10300S","1KVA/1KW","",  "model_code_convention"),
   ("OH1002T10600S","2KVA/2KW","",  "model_code_convention"),
   ("OH1003T10800S","3KVA/3KW","",  "model_code_convention"),
   ("OH1006T11600S","6KVA/6KW","",  "model_code_convention"),
   ("OH1006T12000S","6KVA/6KW","",  "model_code_convention"),
   ("OH1010T11600S","10KVA/10KW","","model_code_convention"),
   ("OH1010T12000S","10KVA/10KW","","model_code_convention"),
 ],
 "PROD-007": [  # T-4003 20-80k: Standard (B) + Long Back-up (S), source-labelled
   ("OH3020T14000B","20kVA/20kW","Standard",   "source_explicit"),
   ("OH3020T14400S","20kVA/20kW","Long Back-up","source_explicit"),
   ("OH3030T14000B","30kVA/30kW","Standard",   "source_explicit"),
   ("OH3030T14400S","30kVA/30kW","Long Back-up","source_explicit"),
   ("OH3040T14000B","40kVA/40kW","Standard",   "source_explicit"),
   ("OH3040T14400S","40kVA/40kW","Long Back-up","source_explicit"),
   ("OH3060T14000B","60kVA/60kW","Standard",   "source_explicit"),
   ("OH3060T14400S","60kVA/60kW","Long Back-up","source_explicit"),
   ("OH3080T14000B","80kVA/80kW","Standard",   "source_explicit"),
   ("OH3080T14400S","80kVA/80kW","Long Back-up","source_explicit"),
 ],
 "PROD-011": [  # T-4101 1-15k: 6kVA has two variants
   ("OL1001T80600S","1KVA/0.8KW","", "model_code_convention"),
   ("OL1002T80600S","2KVA/1.6KW","", "model_code_convention"),
   ("OL1003T80800S","3KVA/2.4KW","", "model_code_convention"),
   ("OL1006T81600S","6KVA/4.8KW","", "model_code_convention"),
   ("OL1006T80800S","6KVA/4.8KW","", "model_code_convention"),
   ("OL1008T81600S","8KVA/6.4KW","", "model_code_convention"),
   ("OL1010T81600S","10KVA/8KW","",  "model_code_convention"),
   ("OL1015T81600S","15KVA/12KW","", "model_code_convention"),
 ],
 "PROD-020": [  # T-4011 6-10k lithium-compatible: capacities inline in source
   ("OH1006R11600L","6kVA/6kW","",  "source_explicit"),
   ("OH1006R16000L","6kVA/6kW","",  "source_explicit"),
   ("OH1010R11600L","10kVA/10kW","","source_explicit"),
   ("OH1010R16000L","10kVA/10kW","","source_explicit"),
   ("OH2010R11600L","10kVA/10kW","","source_explicit"),
 ],
 "PROD-036": [  # Li-ion 48VDC-100Ah: labelled fields
   ("RB-LI-48-100","48VDC / 100Ah","","source_explicit"),
 ],
 "PROD-037": [  # Li-ion pack: RB-LI-{voltage}-{Ah}; voltages 409.8/512, Ah 50/100 per title
   ("RB-LI-410-50","409.8VDC / 50Ah","",  "model_code_convention"),
   ("RB-LI-512-50","512VDC / 50Ah","",    "model_code_convention"),
   ("RB-LI-410-100","409.8VDC / 100Ah","","model_code_convention"),
   ("RB-LI-512-100","512VDC / 100Ah","",  "model_code_convention"),
 ],
 "PROD-039": [  # Li-ion 512VDC-200Ah: labelled
   ("RB-LI-512-200","512VDC / 200Ah","","source_explicit"),
 ],
}

# --- Additional products recovered after widening model-code detection ---
# (These families use prefixes MH/IH/STS that the first-pass regex missed.
#  A few codes appear to be missing a leading 'I' in the source — kept verbatim.)
RESOLVED.update({
 "PROD-025": [  # T-6003 Modular (source lists 200-600kVA modules)
   ("MH3200U15000S","200KVA","","source_explicit"),
   ("MH3300U15000S","300KVA","","source_explicit"),
   ("MH3400U15000S","400KVA","","source_explicit"),
   ("MH3500U15000S","500KVA","","source_explicit"),
   ("MH3600U15000S","600KVA","","source_explicit"),
 ],
 "PROD-026": [  # T-7701 Inverter 1.6-6kVA
   ("IH11X6W10100C","1600VA/1600W","","source_explicit"),
   ("H13X2W10200C","3200VA/3200W","","source_explicit"),
   ("IH1004W10200C","4000VA/4000W","","source_explicit"),
   ("IH1006W10400C","6000VA/6000W","","source_explicit"),
 ],
 "PROD-027": [  # T-7701 Inverter 6-10kVA
   ("IH1006W10400S","6kVA/6kW","","source_explicit"),
   ("IH1008W10400S","8kVA/8kW","","source_explicit"),
   ("H1010W10400S","10kVA/10kW","","source_explicit"),
 ],
 "PROD-028": [  # T-7701 Inverter 3-5kVA (R and W variants share capacity)
   ("IH1003R10200M","3KVA/3KW","","source_explicit"),
   ("IH1003W10200M","3KVA/3KW","","source_explicit"),
   ("IH1005R10400M","5KVA/5KW","","source_explicit"),
   ("IH1005W10400M","5KVA/5KW","","source_explicit"),
 ],
 "PROD-029": [  # T-7701 Inverter 11kVA
   ("IH1011W10400C","11000VA/11000W","","source_explicit"),
 ],
 "PROD-030": [  # T-7703 Three Phase Inverter
   ("H3010W10400M","10kVA/10kW","","source_explicit"),
   ("IH3012W10400M","12kVA/12kW","","source_explicit"),
   ("IH3015W10400M","15kVA/15kW","","source_explicit"),
   ("IH3020W10400M","20kVA/20kW","","source_explicit"),
 ],
 "PROD-031": [  # STS Single Phase (rated in Amps)
   ("STS22016","16A","","source_explicit"),
   ("STS22032","32A","","source_explicit"),
 ],
 "PROD-032": [  # STS Three Phase (rated in Amps)
   ("STS380025","25A","","source_explicit"),
   ("STS380032","32A","","source_explicit"),
   ("STS380045","45A","","source_explicit"),
   ("STS380063","63A","","source_explicit"),
   ("STS380100","100A","","source_explicit"),
   ("STS380160","160A","","source_explicit"),
   ("STS380200","200A","","source_explicit"),
 ],
})
