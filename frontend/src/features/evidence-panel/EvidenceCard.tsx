"use client";

import Image from "next/image";

import { resolveAssetUrl } from "@/lib/api/client";
import type { EvidenceCitation } from "@/lib/api/types";
import { formatTimestamp } from "@/lib/format";

interface EvidenceCardProps {
  citation: EvidenceCitation;
  index: number;
  onSeek(timestampMs: number): void;
}

export function EvidenceCard({ citation, index, onSeek }: EvidenceCardProps) {
  const imageUrl = resolveAssetUrl(citation.snapshot_url);

  return (
    <article className="evidence-card">
      {imageUrl && (
        <button
          aria-label={`跳转到 ${formatTimestamp(citation.timestamp_ms)}`}
          className="evidence-image"
          onClick={() => onSeek(citation.timestamp_ms)}
          type="button"
        >
          <Image
            alt={`视频证据 ${index + 1}`}
            fill
            loading="eager"
            sizes="280px"
            src={imageUrl}
            unoptimized
          />
          <span>{formatTimestamp(citation.timestamp_ms)}</span>
        </button>
      )}
      <button
        className="evidence-copy"
        onClick={() => onSeek(citation.timestamp_ms)}
        type="button"
      >
        <span className="citation-index">{String(index + 1).padStart(2, "0")}</span>
        <span>
          <strong>{formatTimestamp(citation.timestamp_ms)}</strong>
          <small>{citation.label}</small>
        </span>
      </button>
    </article>
  );
}
