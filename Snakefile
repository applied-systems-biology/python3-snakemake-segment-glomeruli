import os
import glob

print("Input read from " + config["input"])
print("Output written to " + config["output"])

if not os.path.exists(config["output"]):
    os.makedirs(config["output"])

# Collect sample information
samples = {}

for sample_name in os.listdir(config["input"]):
    sample_path = config["input"] + "/" + sample_name
    output_path = config["output"] + "/" + sample_name
    if not os.path.isdir(sample_path):
        continue

    slice_names = sorted([os.path.basename(x) for x in glob.glob(sample_path + "/*.tif")])
    zsize = len(slice_names)

    samples[sample_name] = slice_names

    print("Sample " + sample_name + " of size " + str(zsize))

rule all:
    input: expand(config["output"] + "{sample}/glomeruli.json", sample=list(samples.keys()))

def aggr_glomeruli_q(wildcards):
    return [ config["output"] + wildcards["sample"] + "/glomeruli2d/" + x for x in samples[wildcards["sample"]] ]

rule glomeruli_q:
    input: aggr_glomeruli_q
    output: config["output"] + "{sample}/glomeruli.json"

rule glomeruli_2d:
    input:
        config["output"] + "{sample}/tissue.json",
        config["output"] + "{sample}/tissue/{slice}"
    output: config["output"] + "{sample}/glomeruli2d/{slice}"

def aggr_tissue_q(wildcards):
    return [ config["output"] + wildcards["sample"] + "/tissue/" + x for x in samples[wildcards["sample"]] ]

rule tissue_q:
    input: aggr_tissue_q
    output: config["output"] + "{sample}/tissue.json"

rule tissue_2d:
    output: config["output"] + "{sample}/tissue/{slice}"


