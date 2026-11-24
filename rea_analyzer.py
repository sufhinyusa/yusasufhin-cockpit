# -*- coding: utf-8 -*-
"""
rea_analyzer.py — Gerçek Python AST & Desen Tabanlı Güvenlik Analizörü
======================================================================
Eski 4 regex'li ve `hedef` parametresini yok sayan sahte tarayıcının yerine geçer.
Geçerli Python kodunu `ast.parse` ile gerçek sözdizimi ağacında inceler; Python
olmayan metinlerde (JSON/shell/manifest) güvenli kalıp taraması uygular.
"""
from __future__ import annotations

import ast
import re
from typing import Any, Dict, List, Tuple


_SECRET_RE = re.compile(
    r"(?:api[_-]?key|password|passwd|secret|token|private[_-]?key)\s*[:=]\s*['\"][A-Za-z0-9_\-\/+]{8,}['\"]",
    re.IGNORECASE,
)


def _call_name(node: ast.Call) -> str:
    fn = node.func
    if isinstance(fn, ast.Name):
        return fn.id
    if isinstance(fn, ast.Attribute):
        parts = [fn.attr]
        cur = fn.value
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        return ".".join(reversed(parts))
    return ""


def _kw_is_true(node: ast.Call, kw_name: str) -> bool:
    for kw in node.keywords:
        if kw.arg == kw_name and isinstance(kw.value, ast.Constant) and kw.value.value is True:
            return True
    return False


def _analyze_python_ast(source: str) -> Tuple[List[Dict[str, Any]], int, bool]:
    """Python AST ağacında gerçek güvenlik zafiyetlerini tarar."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return [], 100, False

    findings: List[Dict[str, Any]] = []
    score = 100

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _call_name(node)
            line = getattr(node, "lineno", None)
            if name in ("eval", "exec", "compile", "__import__"):
                findings.append({
                    "kural": "Dinamik Kod Çalıştırma (AST)",
                    "ciddiyet": "KRİTİK",
                    "satir": line,
                    "mesaj": f"`{name}()` çağrısı tespit edildi; güvensiz girdi ile uzaktan kod çalıştırmaya yol açar.",
                })
                score -= 35
            elif name in ("os.system", "os.popen"):
                findings.append({
                    "kural": "Shell Komut Enjeksiyonu (AST)",
                    "ciddiyet": "KRİTİK",
                    "satir": line,
                    "mesaj": f"`{name}()` yerine `subprocess.run([...], shell=False)` kullanılmalıdır.",
                })
                score -= 30
            elif name.startswith("subprocess.") and _kw_is_true(node, "shell"):
                findings.append({
                    "kural": "Komut Enjeksiyonu (AST)",
                    "ciddiyet": "YÜKSEK",
                    "satir": line,
                    "mesaj": f"`{name}(..., shell=True)` tespit edildi.",
                })
                score -= 25
            elif name in ("pickle.loads", "pickle.load", "marshal.loads"):
                findings.append({
                    "kural": "Güvensiz Serileştirme (AST)",
                    "ciddiyet": "KRİTİK",
                    "satir": line,
                    "mesaj": f"`{name}()` güvenilmeyen veride keyfi kod çalıştırır; JSON tercih edilmelidir.",
                })
                score -= 30
            elif name == "yaml.load":
                has_safe = any(
                    kw.arg == "Loader" and "Safe" in ast.dump(kw.value)
                    for kw in node.keywords
                )
                if not has_safe:
                    findings.append({
                        "kural": "Güvensiz YAML Yükleme (AST)",
                        "ciddiyet": "YÜKSEK",
                        "satir": line,
                        "mesaj": "`yaml.load()` yerine `yaml.safe_load()` kullanılmalıdır.",
                    })
                    score -= 20
            elif name.endswith(".startswith") and "is_relative_to" not in source:
                findings.append({
                    "kural": "Zayıf Dizin Denetimi (AST)",
                    "ciddiyet": "ORTA",
                    "satir": line,
                    "mesaj": "Dizin sınır denetiminde `startswith` yerine `Path.is_relative_to()` tercih edilmelidir.",
                })
                score -= 10
        elif isinstance(node, ast.ExceptHandler) and node.type is None:
            findings.append({
                "kural": "Geniş Hata Yutma (AST)",
                "ciddiyet": "DÜŞÜK",
                "satir": getattr(node, "lineno", None),
                "mesaj": "Çıplak `except:` bloğu beklenmeyen hataları ve iptalleri gizleyebilir.",
            })
            score -= 5

    return findings, score, True


def analyze_code(target_code: str, persona: str = "kys") -> Dict[str, Any]:
    """Kod veya yapılandırma metnini AST + gizli anahtar taramasıyla analiz eder."""
    text = str(target_code or "").strip()
    if not text:
        return {
            "status": "completed",
            "mode": "empty",
            "persona": persona,
            "score": None,
            "vulnerabilities_found": 0,
            "findings": [],
            "level": "GİRDİ YOK",
            "rapor": "Analiz edilecek kod veya metin sağlanmadı.",
        }

    findings, score, ast_used = _analyze_python_ast(text)

    # AST parse edilemeyen (shell/JS/yarım parça) metinler için desen taraması
    if not ast_used:
        if re.search(r"\b(eval|exec)\s*\(", text):
            findings.append({"kural": "Dinamik Kod Çalıştırma", "ciddiyet": "KRİTİK", "mesaj": "`eval()` veya `exec()` tespit edildi."})
            score -= 35
        if re.search(r"subprocess\.(run|Popen|call)\(.*shell\s*=\s*True", text):
            findings.append({"kural": "Komut Enjeksiyonu", "ciddiyet": "YÜKSEK", "mesaj": "`shell=True` kullanımı tespit edildi."})
            score -= 25
        if re.search(r"\.startswith\(", text) and "is_relative_to" not in text:
            findings.append({"kural": "Zayıf Dizin Denetimi", "ciddiyet": "ORTA", "mesaj": "`startswith` yerine `is_relative_to` önerilir."})
            score -= 10

    # Gizli anahtar / sabit şifre taraması her modda çalışır
    if _SECRET_RE.search(text):
        findings.append({
            "kural": "Hardcoded Secret",
            "ciddiyet": "YÜKSEK",
            "mesaj": "Kod içinde sabit API anahtarı, parola veya token tespit edildi.",
        })
        score -= 20

    score = max(0, min(100, score))
    level = "GÜVENLİ (DÜŞÜK RİSK)" if score >= 90 else ("DİKKAT (ORTA RİSK)" if score >= 70 else "KRİTİK GÜVENSİZ")
    mode = "python_ast" if ast_used else "pattern_scan"

    if findings:
        lines = [
            f"**REA Güvenlik Raporu ({mode})** — Skor: **{score}/100** ({level})",
            "",
        ]
        for f in findings:
            loc = f" (satır {f['satir']})" if f.get("satir") else ""
            lines.append(f"- **[{f['ciddiyet']}] {f['kural']}{loc}:** {f['mesaj']}")
        rapor = "\n".join(lines)
    else:
        rapor = f"**REA Güvenlik Raporu ({mode})** — Skor: **{score}/100** ({level}). Bilinen kritik zafiyet kalıbı tespit edilmedi."

    return {
        "status": "completed",
        "mode": mode,
        "persona": persona,
        "score": score,
        "vulnerabilities_found": len(findings),
        "findings": findings,
        "level": level,
        "rapor": rapor,
    }
