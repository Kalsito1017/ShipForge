{{/*
Common names and labels for the ShipForge chart.
*/}}
{{- define "shipment-platform.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "shipment-platform.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name (include "shipment-platform.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "shipment-platform.labels" -}}
app.kubernetes.io/name: {{ include "shipment-platform.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{- define "shipment-platform.selectorLabels" -}}
app.kubernetes.io/name: {{ include "shipment-platform.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "shipment-platform.api.fullname" -}}
{{- printf "%s-api" (include "shipment-platform.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "shipment-platform.worker.fullname" -}}
{{- printf "%s-worker" (include "shipment-platform.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "shipment-platform.postgres.fullname" -}}
{{- printf "%s-postgres" (include "shipment-platform.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "shipment-platform.redis.fullname" -}}
{{- printf "%s-redis" (include "shipment-platform.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "shipment-platform.minio.fullname" -}}
{{- printf "%s-minio" (include "shipment-platform.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "shipment-platform.configMapName" -}}
{{- printf "%s-config" (include "shipment-platform.fullname" .) -}}
{{- end -}}

{{- define "shipment-platform.secretName" -}}
{{- printf "%s-secrets" (include "shipment-platform.fullname" .) -}}
{{- end -}}

{{/* Shared environment for api and worker containers.
     Note: $(VAR) expansion resolves only against vars defined EARLIER in
     this list — POSTGRES_* must precede DATABASE_URL. */}}
{{- define "shipment-platform.env" -}}
- name: APP_ENV
  valueFrom:
    configMapKeyRef:
      name: {{ include "shipment-platform.configMapName" . }}
      key: APP_ENV
- name: LOG_LEVEL
  valueFrom:
    configMapKeyRef:
      name: {{ include "shipment-platform.configMapName" . }}
      key: LOG_LEVEL
- name: POSTGRES_USER
  valueFrom:
    configMapKeyRef:
      name: {{ include "shipment-platform.configMapName" . }}
      key: POSTGRES_USER
- name: POSTGRES_DB
  valueFrom:
    configMapKeyRef:
      name: {{ include "shipment-platform.configMapName" . }}
      key: POSTGRES_DB
- name: POSTGRES_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ include "shipment-platform.secretName" . }}
      key: POSTGRES_PASSWORD
- name: DATABASE_URL
  value: "postgresql+psycopg://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@{{ include "shipment-platform.postgres.fullname" . }}:{{ .Values.postgres.port }}/$(POSTGRES_DB)"
- name: REDIS_URL
  value: "redis://{{ include "shipment-platform.redis.fullname" . }}:{{ .Values.redis.port }}/0"
- name: MINIO_ENDPOINT
  value: "{{ include "shipment-platform.minio.fullname" . }}:{{ .Values.minio.port }}"
- name: MINIO_SECURE
  value: "false"
- name: MINIO_BUCKET
  value: "artifacts"
- name: MINIO_ACCESS_KEY
  valueFrom:
    secretKeyRef:
      name: {{ include "shipment-platform.secretName" . }}
      key: MINIO_ACCESS_KEY
- name: MINIO_SECRET_KEY
  valueFrom:
    secretKeyRef:
      name: {{ include "shipment-platform.secretName" . }}
      key: MINIO_SECRET_KEY
- name: JWT_SECRET
  valueFrom:
    secretKeyRef:
      name: {{ include "shipment-platform.secretName" . }}
      key: JWT_SECRET
- name: JWT_ALGORITHM
  valueFrom:
    configMapKeyRef:
      name: {{ include "shipment-platform.configMapName" . }}
      key: JWT_ALGORITHM
- name: JWT_EXPIRES_MINUTES
  valueFrom:
    configMapKeyRef:
      name: {{ include "shipment-platform.configMapName" . }}
      key: JWT_EXPIRES_MINUTES
- name: LLM_API_KEY
  valueFrom:
    secretKeyRef:
      name: {{ include "shipment-platform.secretName" . }}
      key: LLM_API_KEY
- name: LLM_BASE_URL
  valueFrom:
    configMapKeyRef:
      name: {{ include "shipment-platform.configMapName" . }}
      key: LLM_BASE_URL
- name: LLM_MODEL
  valueFrom:
    configMapKeyRef:
      name: {{ include "shipment-platform.configMapName" . }}
      key: LLM_MODEL
- name: LLM_TIMEOUT_SECONDS
  valueFrom:
    configMapKeyRef:
      name: {{ include "shipment-platform.configMapName" . }}
      key: LLM_TIMEOUT_SECONDS
- name: ARTIFACT_MAX_SIZE_MB
  valueFrom:
    configMapKeyRef:
      name: {{ include "shipment-platform.configMapName" . }}
      key: ARTIFACT_MAX_SIZE_MB
{{- end -}}
