# SPDX-FileCopyrightText: 2026 ZAL GmbH
# SPDX-License-Identifier: Apache-2.0

from flask import Flask

import config
import utils.aas_utils as aas_utils
import utils.filters as filters
from db import db
from routes.auth import init_auth, nq_bp
from routes.customer import customer_bp
from routes.dataspace import dataspace_bp
from routes.edc import edc_bp
from routes.files import files_bp
from routes.supplier import supplier_bp
from utils import attachments


def create_app():
    app = Flask(__name__)
    app.secret_key = config.SECRET_KEY
    app.config["SESSION_COOKIE_NAME"] = f"session_{config.ROLE}"

    # Field info for form tooltips
    field_info = aas_utils.load_field_info()

    @app.context_processor
    def inject_field_info():
        return {"field_info": field_info}

    app.add_template_filter(filters.format_value, "format_value")
    app.add_template_filter(
        filters.get_disposition_comparisons, "get_disposition_comparisons"
    )
    app.add_template_global(attachments.browser_url, "attachment_url")

    init_auth(app)
    db.init_db()

    # Demo NQs
    from demo.seed import seed_demo_nqs

    seed_demo_nqs()

    app.register_blueprint(nq_bp)
    app.register_blueprint(customer_bp)
    app.register_blueprint(supplier_bp)
    app.register_blueprint(dataspace_bp)
    app.register_blueprint(edc_bp)
    app.register_blueprint(files_bp)

    return app


app = create_app()
