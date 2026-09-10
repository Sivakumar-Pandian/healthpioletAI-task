def next_document_number(db, model, field_name, prefix):
    """Return the next zero-padded document number for a model field."""
    column = getattr(model, field_name)
    existing = db.query(column).filter(column.like(f"{prefix}-%")).all()
    max_num = 0

    for (doc_no,) in existing:
        try:
            max_num = max(max_num, int(doc_no.split("-")[-1]))
        except ValueError:
            continue

    return f"{prefix}-{max_num + 1:04d}"
