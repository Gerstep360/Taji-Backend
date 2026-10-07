from security.models import AccessEvent, VisitAuthorization
from security.serializers import AccessEventSerializer, VisitAuthorizationSummarySerializer


def identity(event):
    authorization = event.authorization
    person_id = event.person_id or (authorization.visitor_person_id if authorization else None)
    if person_id:
        return ("person", person_id)
    if authorization:
        return ("authorization", authorization.pk)
    if event.visitor_document_number.strip():
        return ("document", event.visitor_document_number.strip().casefold(), event.unit_id)
    return ("event", event.pk)


def movement_row(event):
    data = dict(AccessEventSerializer(event).data)
    authorization = event.authorization
    person = event.person or (authorization.visitor_person if authorization else None)
    unit = event.unit or (authorization.unit if authorization else None)
    data.update(
        visitor_name=person.full_name if person else event.visitor_name,
        visitor_document_number=(person.document_number or "") if person else event.visitor_document_number,
        unit_code=unit.code if unit else "",
        entered_at=event.occurred_at.isoformat() if event.event_type == AccessEvent.Type.ENTRY else None,
    )
    return data


def consultation(authorizations, events, section, now):
    latest = {}
    entered = set()
    authorization_latest = {}
    open_authorizations = {}
    for event in events.filter(
        validation_result=AccessEvent.Result.APPROVED,
        event_type__in=[AccessEvent.Type.ENTRY, AccessEvent.Type.EXIT],
        occurred_at__lte=now,
    ).order_by("occurred_at", "id").iterator():
        key = identity(event)
        latest[key] = event
        if event.event_type == AccessEvent.Type.EXIT:
            previous_authorization = open_authorizations.pop(key, None)
            if previous_authorization:
                authorization_latest[previous_authorization] = event
        if event.authorization_id:
            authorization_latest[event.authorization_id] = event
            if event.event_type == AccessEvent.Type.ENTRY:
                entered.add(event.authorization_id)
                open_authorizations[key] = event.authorization_id
    if section == "history":
        return [movement_row(event) for event in events.filter(occurred_at__lte=now).order_by("-occurred_at", "-id")]
    if section == "inside":
        return [movement_row(event) for event in sorted(latest.values(), key=lambda e: (e.occurred_at, e.id), reverse=True)
                if event.event_type == AccessEvent.Type.ENTRY]
    rows = []
    for authorization in authorizations.order_by("-valid_from", "-id"):
        last = authorization_latest.get(authorization.id)
        terminal = authorization.status in (
            VisitAuthorization.Status.FINISHED, VisitAuthorization.Status.CANCELLED, VisitAuthorization.Status.EXPIRED,
        )
        inside = latest.get(("person", authorization.visitor_person_id))
        active = bool(not terminal and authorization.valid_from <= now < authorization.valid_until
                      and last and last.event_type == AccessEvent.Type.ENTRY and inside
                      and inside.event_type == AccessEvent.Type.ENTRY and inside.authorization_id == authorization.id)
        finished = terminal or now >= authorization.valid_until or bool(
            authorization.id in entered and last and last.event_type == AccessEvent.Type.EXIT
        )
        expected = (not terminal and now < authorization.valid_until
                    and authorization.id not in entered)
        if {"expected": expected, "active": active, "finished": finished}[section]:
            data = dict(VisitAuthorizationSummarySerializer(authorization).data)
            data.update(visitor_name=authorization.visitor_person.full_name,
                        visitor_document_number=authorization.visitor_person.document_number or "",
                        unit_code=authorization.unit.code,
                        resident_name=authorization.authorized_by_resident.person.full_name,
                        last_movement=last.event_type if last else None,
                        entered_at=last.occurred_at.isoformat() if active else None)
            rows.append(data)
    return rows
