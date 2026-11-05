/**
 * One library file in the inspector: its label, its path, its text shown as text (never rendered
 * as markup), its size and digest with the file as its source, and every promotion line naming
 * it in log order, the one that wrote these bytes marked. A line with no digest says so.
 */
import { fileRoute, type LibraryFile, libraryFile } from "../../api/library";
import { Id } from "../../design/components/data/Id";
import { Quantity } from "../../design/components/data/Quantity";
import { SourceChip } from "../../design/components/data/SourceChip";
import { sourceAttribute } from "../../design/components/data/source";
import { Inspector, InspectorSection } from "../../design/components/layout/Inspector";
import { ErrorState, LoadingState } from "../../design/components/status/States";
import { StatusTag } from "../../design/components/status/StatusTag";
import { documentLabel, LIBRARY_COPY } from "../../words/library";
import { useJson } from "../common/read";
import { STATE_TAGS } from "./model";
import { PromotedAt, PromotedBy, RoleTag, ShortDigest, useFocusOnOpen } from "./parts";

export function DocumentInspector({
  kind,
  role,
}: {
  readonly kind: string;
  readonly role: string;
}) {
  const read = useJson(fileRoute(kind, role), libraryFile);
  const label = documentLabel(kind, role);
  const focus = useFocusOnOpen(`${kind}/${role}`);
  const file = read.result?.ok === true ? read.result.value : null;
  return (
    <Inspector
      label="Library file"
      crumbs={["Library"]}
      title={
        <span ref={focus} tabIndex={-1} className="pg-lib-focus">
          {label}
        </span>
      }
      badges={
        <>
          <RoleTag role={role} />
          {file !== null && <StatusTag status={STATE_TAGS[file.state]} />}
        </>
      }
    >
      {read.result === null ? (
        <LoadingState reading={LIBRARY_COPY.reading} rows={3} />
      ) : !read.result.ok ? (
        <ErrorState
          title={LIBRARY_COPY.fileError}
          {...read.result.refusal}
          route={read.route}
          onRetry={read.again}
        />
      ) : (
        <FileBody file={read.result.value} />
      )}
    </Inspector>
  );
}

function FileBody({ file }: { readonly file: LibraryFile }) {
  return (
    <div data-source={sourceAttribute({ id: file.path, commit: null })}>
      <InspectorSection label="File">
        <Id value={file.path} />
      </InspectorSection>
      <InspectorSection label="Text">
        <div className="pg-lib-text">{file.text}</div>
      </InspectorSection>
      <InspectorSection label="Fingerprint">
        <dl className="pg-facts">
          <dt>Size</dt>
          <dd data-fact="size">
            <Quantity value={file.size} unit="B" />
          </dd>
          <dt>sha256</dt>
          <dd>
            <Id value={file.sha256} />
          </dd>
          <dt>Source</dt>
          <dd>
            <SourceChip id={file.path} commit={null} compact />
          </dd>
        </dl>
      </InspectorSection>
      <InspectorSection label="Promotion history">
        {file.promotions.length === 0 ? (
          <p className="pg-muted">{LIBRARY_COPY.noHistory}</p>
        ) : (
          <ol className="pg-list pg-lib-history">
            {file.promotions.map((line, index) => (
              <li key={`${String(index)}-${line.candidateId ?? ""}`} className="pg-list-row">
                <span className="pg-list-row-main">
                  <span className="pg-lib-history-when">
                    <PromotedAt line={line} />
                    <PromotedBy line={line} />
                  </span>
                  {line.sha256 === null ? (
                    <span className="pg-muted">{LIBRARY_COPY.noDigest}</span>
                  ) : (
                    <ShortDigest value={line.sha256} />
                  )}
                </span>
                {file.wrote === index && <StatusTag status="wrote-this-file" strong />}
              </li>
            ))}
          </ol>
        )}
      </InspectorSection>
    </div>
  );
}
