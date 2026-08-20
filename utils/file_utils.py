# SPDX-FileCopyrightText: 2026 ZAL GmbH
# SPDX-License-Identifier: Apache-2.0

import json


def read_json(json_file_path):
    try:
        with open(json_file_path, "r") as file:
            payload = json.load(file)
    except FileNotFoundError:
        print(f"Error: The file {json_file_path} was not found.")
        exit(1)
    return payload


def read_file(path):
    config = {}
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                config[key.strip()] = value.strip()
    return config


def write_file(path, config):
    with open(path, "w") as f:
        for key, value in config.items():
            f.write(f"{key}={value}\n")


def inject_ssh_properties(yaml_data, conf_data):
    mapping_dict = {
        "IATP ID": "edc.iam.issuer.id",
        "DIM URL": "tx.edc.iam.sts.dim.url",
        "Trusted Issuers": "edc.iam.trusted-issuer.issuer.id",
        "BPNL-DID Resolution Service (bdrs server url)": "tx.edc.iam.iatp.bdrs.server.url",
        "OAuth Client ID": "edc.iam.sts.oauth.client.id",
        "OAuth Token URL": "edc.iam.sts.oauth.token.url",
        "BPN": "edc.participant.id",
    }

    for key, value in mapping_dict.items():
        conf_data[value] = yaml_data[key]
    write_file("./config/_tmp.properties", conf_data)
    return "./config/_tmp.properties"
