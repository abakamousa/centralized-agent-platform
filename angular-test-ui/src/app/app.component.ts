import { CommonModule } from "@angular/common";
import { HttpClient, HttpHeaders } from "@angular/common/http";
import { Component, inject, signal } from "@angular/core";
import { FormsModule } from "@angular/forms";
import YAML from "yaml";

type Mode = "saved-app" | "yaml-preview";

interface AppSummary {
  application_id: string;
  display_name: string;
  source: string;
}

@Component({
  selector: "app-root",
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <main class="page-shell">
      <section class="hero">
        <p class="eyebrow">Angular Test Console</p>
        <h1>Centralized Agent Platform Playground</h1>
        <p class="hero-copy">
          Test saved app definitions or paste YAML directly to preview a workflow without
          publishing it first.
        </p>
      </section>

      <section class="control-grid">
        <div class="panel">
          <h2>Mode</h2>
          <div class="mode-switch">
            <button
              type="button"
              [class.active]="mode() === 'saved-app'"
              (click)="setMode('saved-app')"
            >
              Saved App
            </button>
            <button
              type="button"
              [class.active]="mode() === 'yaml-preview'"
              (click)="setMode('yaml-preview')"
            >
              YAML Preview
            </button>
          </div>

          <label>
            Bearer Token
            <textarea
              rows="4"
              [(ngModel)]="authToken"
              placeholder="Paste an Auth0 bearer token"
            ></textarea>
          </label>

          <div class="field-row">
            <label>
              Session ID
              <input [(ngModel)]="sessionId" placeholder="session-123" />
            </label>
            <label>
              Thread ID
              <input [(ngModel)]="threadId" placeholder="Optional explicit thread id" />
            </label>
          </div>

          <label>
            User Input
            <textarea
              rows="6"
              [(ngModel)]="userInput"
              placeholder="Type the message to send to the workflow"
            ></textarea>
          </label>

          <div *ngIf="mode() === 'saved-app'" class="stack">
            <label>
              Application
              <select [(ngModel)]="selectedApplicationId" (change)="loadSelectedApp()">
                <option value="">Select an application</option>
                <option *ngFor="let app of applications()" [value]="app.application_id">
                  {{ app.display_name }} ({{ app.application_id }})
                </option>
              </select>
            </label>
            <button type="button" class="secondary" (click)="loadSelectedApp()">
              Load Config
            </button>
          </div>

          <div *ngIf="mode() === 'yaml-preview'" class="stack">
            <div class="upload-row">
              <label class="file-upload">
                <span>Load YAML File</span>
                <input
                  type="file"
                  accept=".yaml,.yml,text/yaml,application/x-yaml"
                  (change)="loadYamlFile($event)"
                />
              </label>
              <button type="button" class="secondary" (click)="clearYaml()">
                Clear YAML
              </button>
            </div>
            <label>
              YAML Config
              <textarea
                rows="18"
                [(ngModel)]="yamlConfig"
                placeholder="Paste an app YAML definition"
              ></textarea>
            </label>
          </div>

          <div class="action-row">
            <button type="button" (click)="invoke()">Run Request</button>
            <button type="button" class="secondary" (click)="resetResponse()">Clear Response</button>
          </div>
        </div>

        <div class="panel">
          <h2>Config Preview</h2>
          <pre>{{ configPreview() }}</pre>
        </div>

        <div class="panel response-panel">
          <div class="response-head">
            <h2>Response</h2>
            <span class="status" [class.error]="!!errorMessage()">
              {{ errorMessage() ? 'Error' : 'Ready' }}
            </span>
          </div>

          <p *ngIf="errorMessage()" class="error-text">{{ errorMessage() }}</p>
          <pre *ngIf="responseBody()">{{ responseBody() }}</pre>
          <p *ngIf="!responseBody() && !errorMessage()" class="placeholder">
            Run a request to inspect the workflow response, memory state, guardrail findings,
            and preview output.
          </p>
        </div>
      </section>
    </main>
  `,
  styles: [
    `
      :host {
        display: block;
      }
    `,
  ],
})
export class AppComponent {
  private readonly http = inject(HttpClient);

  readonly mode = signal<Mode>("saved-app");
  readonly applications = signal<AppSummary[]>([]);
  readonly loadedConfig = signal<Record<string, unknown> | null>(null);
  readonly responseBody = signal<string>("");
  readonly errorMessage = signal<string>("");

  authToken = "";
  sessionId = "";
  threadId = "";
  userInput = "";
  selectedApplicationId = "";
  yamlConfig = "";

  constructor() {
    this.loadApplications();
  }

  configPreview(): string {
    if (this.mode() === "yaml-preview") {
      return this.yamlConfig || "Paste YAML to preview it here.";
    }

    const loaded = this.loadedConfig();
    return loaded ? YAML.stringify(loaded) : "Select a saved app to inspect its config.";
  }

  setMode(mode: Mode): void {
    this.mode.set(mode);
    this.resetResponse();
  }

  loadApplications(): void {
    this.http.get<{ applications: AppSummary[] }>("/api/apps").subscribe({
      next: (payload) => {
        this.applications.set(payload.applications);
      },
      error: (error: unknown) => {
        this.errorMessage.set(this.extractError(error));
      },
    });
  }

  loadSelectedApp(): void {
    if (!this.selectedApplicationId) {
      this.loadedConfig.set(null);
      return;
    }

    this.http.get<Record<string, unknown>>(`/api/apps/${this.selectedApplicationId}`).subscribe({
      next: (payload) => {
        this.loadedConfig.set(payload);
        this.yamlConfig = YAML.stringify(payload);
      },
      error: (error: unknown) => {
        this.errorMessage.set(this.extractError(error));
      },
    });
  }

  invoke(): void {
    this.resetResponse();
    const headers = this.buildHeaders();

    if (this.mode() === "yaml-preview") {
      this.http
        .post(
          "/api/preview/invoke",
          {
            app_config_yaml: this.yamlConfig,
            input: this.userInput,
            session_id: this.sessionId || undefined,
            thread_id: this.threadId || undefined,
          },
          { headers },
        )
        .subscribe({
          next: (payload) => this.responseBody.set(JSON.stringify(payload, null, 2)),
          error: (error: unknown) => this.errorMessage.set(this.extractError(error)),
        });
      return;
    }

    this.http
      .post(
        "/api/invoke",
        {
          application_id: this.selectedApplicationId,
          input: this.userInput,
          session_id: this.sessionId || undefined,
          thread_id: this.threadId || undefined,
        },
        { headers },
      )
      .subscribe({
        next: (payload) => this.responseBody.set(JSON.stringify(payload, null, 2)),
        error: (error: unknown) => this.errorMessage.set(this.extractError(error)),
      });
  }

  resetResponse(): void {
    this.responseBody.set("");
    this.errorMessage.set("");
  }

  loadYamlFile(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) {
      return;
    }

    const reader = new FileReader();
    reader.onload = () => {
      const content = typeof reader.result === "string" ? reader.result : "";
      this.yamlConfig = content;
      this.loadedConfig.set(null);
      this.resetResponse();
    };
    reader.onerror = () => {
      this.errorMessage.set("Unable to read the selected YAML file.");
    };
    reader.readAsText(file);
    input.value = "";
  }

  clearYaml(): void {
    this.yamlConfig = "";
    this.resetResponse();
  }

  private buildHeaders(): HttpHeaders {
    let headers = new HttpHeaders();
    if (this.authToken.trim()) {
      headers = headers.set("Authorization", this.authToken.trim());
    }
    if (this.sessionId.trim()) {
      headers = headers.set("X-Session-Id", this.sessionId.trim());
    }
    return headers;
  }

  private extractError(error: unknown): string {
    if (
      typeof error === "object" &&
      error !== null &&
      "error" in error &&
      typeof (error as { error?: unknown }).error === "object"
    ) {
      const payload = (error as { error?: { detail?: unknown } }).error;
      if (payload && typeof payload.detail === "string") {
        return payload.detail;
      }
    }

    return "Request failed. Check that agent-core is running and your token is valid.";
  }
}
