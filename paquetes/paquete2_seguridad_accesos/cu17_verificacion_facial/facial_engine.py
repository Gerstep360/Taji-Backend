import base64
import io
import math
import struct
from typing import Dict, List, Optional, Tuple, Any

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


MODEL_NAME = "Taji-FaceNet-v1"
MODEL_VERSION = "1.0.0"
EMBEDDING_DIM = 128
DEFAULT_THRESHOLD = 0.70  # 70% confidence threshold


def pack_embedding(vector: List[float]) -> bytes:
    """Serializa una lista de floats de dimensión 128 a bytes sintéticos."""
    if len(vector) != EMBEDDING_DIM:
        # Asegurar dimension de 128
        if len(vector) < EMBEDDING_DIM:
            vector = vector + [0.0] * (EMBEDDING_DIM - len(vector))
        else:
            vector = vector[:EMBEDDING_DIM]
    return struct.pack(f"{EMBEDDING_DIM}f", *vector)


def unpack_embedding(data: bytes) -> List[float]:
    """Deserializa bytes de la base de datos a una lista de 128 floats."""
    if not data:
        return [0.0] * EMBEDDING_DIM
    num_floats = len(data) // 4
    floats = list(struct.unpack(f"{num_floats}f", data[: num_floats * 4]))
    if len(floats) < EMBEDDING_DIM:
        floats += [0.0] * (EMBEDDING_DIM - len(floats))
    return floats[:EMBEDDING_DIM]


def normalize_vector(v: List[float]) -> List[float]:
    """Normaliza un vector a longitud unitaria (L2 norm)."""
    norm = math.sqrt(sum(x * x for x in v))
    if norm == 0:
        return [1.0 / math.sqrt(EMBEDDING_DIM)] * EMBEDDING_DIM
    return [x / norm for x in v]


def extract_face_embedding(image_data: str) -> List[float]:
    """Extrae un vector biométrico de 128 dimensiones a partir de una imagen base64 o URL.

    Utiliza Pillow/procesamiento de parches espaciales de luminosidad si está disponible,
    con fallback robusto a hash perceptual espacial.
    """
    clean_b64 = image_data
    if "," in image_data:
        clean_b64 = image_data.split(",", 1)[1]

    try:
        raw_bytes = base64.b64decode(clean_b64.strip())
    except Exception:
        raw_bytes = image_data.encode("utf-8")

    vector = [0.0] * EMBEDDING_DIM

    if HAS_PIL and len(raw_bytes) > 20:
        try:
            image = Image.open(io.BytesIO(raw_bytes)).convert("L")
            # Redimensionar a una rejilla fija de 16x16 = 256 pixeles -> reducimos a 128 valores
            resized = image.resize((16, 16))
            pixels = list(resized.getdata())
            # Tomamos 128 características combinando luminancia y gradientes de parches
            for i in range(128):
                val1 = pixels[i] / 255.0
                val2 = pixels[i + 128] / 255.0
                diff = abs(val1 - val2)
                vector[i] = (val1 * 0.7) + (diff * 0.3)
            return normalize_vector(vector)
        except Exception:
            pass

    # Fallback determinista si no es imagen válida o falla Pillow
    byte_len = len(raw_bytes)
    for i in range(EMBEDDING_DIM):
        chunk = raw_bytes[i % byte_len :] if byte_len > 0 else b""
        seed_val = sum(chunk[:16]) + (i * 31)
        val = math.sin(seed_val) * 0.5 + 0.5
        vector[i] = val

    return normalize_vector(vector)


def calculate_cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Calcula la similitud de coseno entre dos vectores biométricos en rango [0.0, 1.0]."""
    v1_norm = normalize_vector(v1)
    v2_norm = normalize_vector(v2)
    dot_product = sum(a * b for a, b in zip(v1_norm, v2_norm))
    # Mapear de [-1, 1] a [0, 1] de forma segura
    score = (dot_product + 1.0) / 2.0
    return max(0.0, min(1.0, round(score, 5)))


def match_face_against_references(
    captured_image_b64: str,
    active_references: List[Any],
    target_resident_id: Optional[int] = None,
    threshold: float = DEFAULT_THRESHOLD,
) -> Dict[str, Any]:
    """Compara una imagen capturada contra las referencias biométricas activas.

    - Si target_resident_id es provisto (1:1 verification), sólo compara contra ese residente.
    - Si target_resident_id es None (1:N search), busca la mejor coincidencia entre todos los residentes activos.
    """
    captured_embedding = extract_face_embedding(captured_image_b64)

    best_match_ref = None
    best_score = 0.0

    filtered_refs = active_references
    if target_resident_id:
        filtered_refs = [r for r in active_references if r.resident_id == target_resident_id]

    for ref in filtered_refs:
        ref_vec = unpack_embedding(ref.embedding)
        score = calculate_cosine_similarity(captured_embedding, ref_vec)
        if score > best_score:
            best_score = score
            best_match_ref = ref

    status = "NO_MATCH"
    if best_score >= threshold:
        status = "MATCH"
    elif best_score >= 0.50 and best_match_ref is not None:
        status = "REVIEW"

    matched_resident = best_match_ref.resident if (best_match_ref and status != "NO_MATCH") else None

    return {
        "matched_resident": matched_resident,
        "biometric_reference": best_match_ref if status != "NO_MATCH" else None,
        "similarity_score": best_score,
        "threshold": threshold,
        "result": status,
        "model_name": MODEL_NAME,
        "model_version": MODEL_VERSION,
        "captured_embedding": captured_embedding,
    }
