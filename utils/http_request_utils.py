# SPDX-FileCopyrightText: 2026 ZAL GmbH
# SPDX-License-Identifier: Apache-2.0

import json

import requests
from flask import request


def get_attached_files_metatdata(form_id: str):
    files = request.files.getlist(form_id)
    attached_files = []
    for f in files:
        if f and f.filename:
            attached_files.append(
                {
                    "filename": f.filename,
                    "content_type": f.content_type,
                }
            )
    return attached_files


def get_post(url, payload=None, header: dict = None, verbose=True, params=None):
    headers = {}
    headers = {"X-Api-Key": "MKrcSOOk"}
    if header != None:
        headers.update(header)
    try:
        if payload != None:
            headers.update({"Content-Type": "application/json"})
            response = requests.post(url, headers=headers, json=payload, verify=False)
        else:
            if params != None:
                headers = headers = header
                response = requests.get(url, headers=headers, verify=False)
            else:
                response = requests.get(url, headers=headers, verify=False)
        response.raise_for_status()  # Will raise an exception for HTTP errors
        response = response.json()
        if verbose:
            print("Response:")
            print(json.dumps(response, indent=2))
    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")
    return response
