import { Tag } from "antd";

import {
  ingestLabel,
  type Label,
  languageLabel,
  priorityLabel,
  serviceRequestLabel,
  stageLabel,
} from "../domain/labels";

const LabelTag = ({ label }: { label: Label }) => <Tag color={label.color}>{label.label}</Tag>;

export const StageBadge = ({ stage }: { stage: string }) => <LabelTag label={stageLabel(stage)} />;

export const PriorityTag = ({ priority }: { priority: string }) => (
  <LabelTag label={priorityLabel(priority)} />
);

export const IngestTag = ({ status }: { status: string }) => (
  <LabelTag label={ingestLabel(status)} />
);

export const RequestStatusTag = ({ status }: { status: string }) => (
  <LabelTag label={serviceRequestLabel(status)} />
);

/** Язык всегда одинаково: RU / UZ / EN. */
export const LangTag = ({ language }: { language: string }) => (
  <Tag bordered={false}>{languageLabel(language)}</Tag>
);
