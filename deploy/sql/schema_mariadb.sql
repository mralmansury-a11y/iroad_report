CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 6818f5288d1c

CREATE TABLE permissions (
    id INTEGER NOT NULL AUTO_INCREMENT, 
    code VARCHAR(64) NOT NULL, 
    description VARCHAR(255), 
    CONSTRAINT pk_permissions PRIMARY KEY (id), 
    CONSTRAINT uq_permissions_code UNIQUE (code)
);

CREATE TABLE report_statuses (
    id INTEGER NOT NULL AUTO_INCREMENT, 
    code VARCHAR(24) NOT NULL, 
    sort_order SMALLINT NOT NULL, 
    tone VARCHAR(16) NOT NULL, 
    is_final BOOL NOT NULL, 
    CONSTRAINT pk_report_statuses PRIMARY KEY (id), 
    CONSTRAINT uq_report_statuses_code UNIQUE (code)
);

CREATE TABLE road_points (
    id INTEGER NOT NULL AUTO_INCREMENT, 
    km NUMERIC(7, 2) NOT NULL, 
    latitude NUMERIC(9, 6) NOT NULL, 
    longitude NUMERIC(9, 6) NOT NULL, 
    label VARCHAR(120), 
    CONSTRAINT pk_road_points PRIMARY KEY (id), 
    CONSTRAINT uq_road_points_km UNIQUE (km)
);

CREATE TABLE road_sections (
    id INTEGER NOT NULL AUTO_INCREMENT, 
    code VARCHAR(32) NOT NULL, 
    km_start NUMERIC(7, 2) NOT NULL, 
    km_end NUMERIC(7, 2) NOT NULL, 
    sort_order INTEGER NOT NULL, 
    is_active BOOL NOT NULL, 
    road_status VARCHAR(16) NOT NULL, 
    visibility_pct SMALLINT, 
    condition_updated_at DATETIME, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    CONSTRAINT pk_road_sections PRIMARY KEY (id), 
    CONSTRAINT ck_road_sections_km_range CHECK (km_end >= km_start), 
    CONSTRAINT ck_road_sections_visibility_range CHECK (visibility_pct IS NULL OR (visibility_pct >= 0 AND visibility_pct <= 100)), 
    CONSTRAINT uq_road_sections_code UNIQUE (code)
);

CREATE INDEX ix_road_sections_created_at ON road_sections (created_at);

CREATE TABLE roles (
    id INTEGER NOT NULL AUTO_INCREMENT, 
    code VARCHAR(32) NOT NULL, 
    level SMALLINT NOT NULL, 
    name_ar VARCHAR(64) NOT NULL, 
    name_en VARCHAR(64) NOT NULL, 
    CONSTRAINT pk_roles PRIMARY KEY (id), 
    CONSTRAINT uq_roles_code UNIQUE (code)
);

CREATE TABLE teams (
    id INTEGER NOT NULL AUTO_INCREMENT, 
    code VARCHAR(32) NOT NULL, 
    is_active BOOL NOT NULL, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    CONSTRAINT pk_teams PRIMARY KEY (id), 
    CONSTRAINT uq_teams_code UNIQUE (code)
);

CREATE INDEX ix_teams_created_at ON teams (created_at);

CREATE TABLE report_categories (
    id INTEGER NOT NULL AUTO_INCREMENT, 
    code VARCHAR(32) NOT NULL, 
    icon VARCHAR(48) NOT NULL, 
    sort_order INTEGER NOT NULL, 
    is_active BOOL NOT NULL, 
    default_team_id INTEGER, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    CONSTRAINT pk_report_categories PRIMARY KEY (id), 
    CONSTRAINT fk_report_categories_default_team_id_teams FOREIGN KEY(default_team_id) REFERENCES teams (id) ON DELETE SET NULL, 
    CONSTRAINT uq_report_categories_code UNIQUE (code)
);

CREATE INDEX ix_report_categories_created_at ON report_categories (created_at);

CREATE INDEX ix_report_categories_is_active ON report_categories (is_active);

CREATE TABLE report_status_translations (
    id INTEGER NOT NULL AUTO_INCREMENT, 
    status_id INTEGER NOT NULL, 
    locale VARCHAR(5) NOT NULL, 
    name VARCHAR(64) NOT NULL, 
    CONSTRAINT pk_report_status_translations PRIMARY KEY (id), 
    CONSTRAINT fk_report_status_translations_status_id_report_statuses FOREIGN KEY(status_id) REFERENCES report_statuses (id) ON DELETE CASCADE, 
    CONSTRAINT uq_status_locale UNIQUE (status_id, locale)
);

CREATE TABLE road_section_translations (
    id INTEGER NOT NULL AUTO_INCREMENT, 
    section_id INTEGER NOT NULL, 
    locale VARCHAR(5) NOT NULL, 
    name VARCHAR(120) NOT NULL, 
    description VARCHAR(500), 
    CONSTRAINT pk_road_section_translations PRIMARY KEY (id), 
    CONSTRAINT fk_road_section_translations_section_id_road_sections FOREIGN KEY(section_id) REFERENCES road_sections (id) ON DELETE CASCADE, 
    CONSTRAINT uq_section_locale UNIQUE (section_id, locale)
);

CREATE TABLE role_permissions (
    role_id INTEGER NOT NULL, 
    permission_id INTEGER NOT NULL, 
    CONSTRAINT pk_role_permissions PRIMARY KEY (role_id, permission_id), 
    CONSTRAINT fk_role_permissions_permission_id_permissions FOREIGN KEY(permission_id) REFERENCES permissions (id) ON DELETE CASCADE, 
    CONSTRAINT fk_role_permissions_role_id_roles FOREIGN KEY(role_id) REFERENCES roles (id) ON DELETE CASCADE
);

CREATE TABLE team_translations (
    id INTEGER NOT NULL AUTO_INCREMENT, 
    team_id INTEGER NOT NULL, 
    locale VARCHAR(5) NOT NULL, 
    name VARCHAR(120) NOT NULL, 
    description VARCHAR(500), 
    CONSTRAINT pk_team_translations PRIMARY KEY (id), 
    CONSTRAINT fk_team_translations_team_id_teams FOREIGN KEY(team_id) REFERENCES teams (id) ON DELETE CASCADE, 
    CONSTRAINT uq_team_locale UNIQUE (team_id, locale)
);

CREATE TABLE users (
    id INTEGER NOT NULL AUTO_INCREMENT, 
    full_name VARCHAR(120) NOT NULL, 
    phone VARCHAR(20), 
    email VARCHAR(255), 
    password_hash VARCHAR(255) NOT NULL, 
    locale VARCHAR(5) NOT NULL, 
    home_section_id INTEGER, 
    job_title VARCHAR(120), 
    is_active BOOL NOT NULL, 
    points INTEGER NOT NULL, 
    last_login_at DATETIME, 
    password_changed_at DATETIME, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    CONSTRAINT pk_users PRIMARY KEY (id), 
    CONSTRAINT ck_users_contact_present CHECK (phone IS NOT NULL OR email IS NOT NULL), 
    CONSTRAINT fk_users_home_section_id_road_sections FOREIGN KEY(home_section_id) REFERENCES road_sections (id) ON DELETE SET NULL, 
    CONSTRAINT uq_users_email UNIQUE (email), 
    CONSTRAINT uq_users_phone UNIQUE (phone)
);

CREATE INDEX ix_users_created_at ON users (created_at);

CREATE INDEX ix_users_is_active ON users (is_active);

CREATE TABLE announcements (
    id INTEGER NOT NULL AUTO_INCREMENT, 
    kind VARCHAR(16) NOT NULL, 
    km_from NUMERIC(7, 2), 
    km_to NUMERIC(7, 2), 
    road_section_id INTEGER, 
    starts_at DATETIME NOT NULL, 
    ends_at DATETIME, 
    is_published BOOL NOT NULL, 
    notified_at DATETIME, 
    created_by_id INTEGER, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    CONSTRAINT pk_announcements PRIMARY KEY (id), 
    CONSTRAINT fk_announcements_created_by_id_users FOREIGN KEY(created_by_id) REFERENCES users (id) ON DELETE SET NULL, 
    CONSTRAINT fk_announcements_road_section_id_road_sections FOREIGN KEY(road_section_id) REFERENCES road_sections (id) ON DELETE SET NULL
);

CREATE INDEX ix_announcements_created_at ON announcements (created_at);

CREATE INDEX ix_announcements_is_published ON announcements (is_published);

CREATE INDEX ix_announcements_kind ON announcements (kind);

CREATE TABLE api_tokens (
    id INTEGER NOT NULL AUTO_INCREMENT, 
    user_id INTEGER NOT NULL, 
    token_hash VARCHAR(64) NOT NULL, 
    name VARCHAR(80), 
    created_at DATETIME NOT NULL, 
    expires_at DATETIME NOT NULL, 
    last_used_at DATETIME, 
    revoked BOOL NOT NULL, 
    CONSTRAINT pk_api_tokens PRIMARY KEY (id), 
    CONSTRAINT fk_api_tokens_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT uq_api_tokens_token_hash UNIQUE (token_hash)
);

CREATE INDEX ix_api_tokens_user_id ON api_tokens (user_id);

CREATE TABLE audit_logs (
    id BIGINT NOT NULL AUTO_INCREMENT, 
    user_id INTEGER, 
    action VARCHAR(64) NOT NULL, 
    entity_type VARCHAR(32), 
    entity_id VARCHAR(32), 
    details JSON, 
    ip_address VARCHAR(45), 
    user_agent VARCHAR(255), 
    created_at DATETIME NOT NULL, 
    CONSTRAINT pk_audit_logs PRIMARY KEY (id), 
    CONSTRAINT fk_audit_logs_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_audit_logs_action ON audit_logs (action);

CREATE INDEX ix_audit_logs_created_at ON audit_logs (created_at);

CREATE INDEX ix_audit_logs_entity_type ON audit_logs (entity_type);

CREATE INDEX ix_audit_logs_user_id ON audit_logs (user_id);

CREATE TABLE contact_messages (
    id INTEGER NOT NULL AUTO_INCREMENT, 
    user_id INTEGER, 
    name VARCHAR(120) NOT NULL, 
    contact VARCHAR(255) NOT NULL, 
    body TEXT NOT NULL, 
    status VARCHAR(12) NOT NULL, 
    reply TEXT, 
    handled_by_id INTEGER, 
    created_at DATETIME NOT NULL, 
    handled_at DATETIME, 
    CONSTRAINT pk_contact_messages PRIMARY KEY (id), 
    CONSTRAINT fk_contact_messages_handled_by_id_users FOREIGN KEY(handled_by_id) REFERENCES users (id) ON DELETE SET NULL, 
    CONSTRAINT fk_contact_messages_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_contact_messages_created_at ON contact_messages (created_at);

CREATE INDEX ix_contact_messages_status ON contact_messages (status);

CREATE INDEX ix_contact_messages_user_id ON contact_messages (user_id);

CREATE TABLE notification_preferences (
    id INTEGER NOT NULL AUTO_INCREMENT, 
    user_id INTEGER NOT NULL, 
    report_updates BOOL NOT NULL, 
    weather_alerts BOOL NOT NULL, 
    project_updates BOOL NOT NULL, 
    points_rewards BOOL NOT NULL, 
    sound BOOL NOT NULL, 
    push_enabled BOOL NOT NULL, 
    CONSTRAINT pk_notification_preferences PRIMARY KEY (id), 
    CONSTRAINT fk_notification_preferences_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT uq_notification_preferences_user_id UNIQUE (user_id)
);

CREATE TABLE push_subscriptions (
    id INTEGER NOT NULL AUTO_INCREMENT, 
    user_id INTEGER, 
    endpoint TEXT NOT NULL, 
    endpoint_hash VARCHAR(64) NOT NULL, 
    p256dh VARCHAR(255) NOT NULL, 
    auth VARCHAR(255) NOT NULL, 
    locale VARCHAR(5) NOT NULL, 
    user_agent VARCHAR(255), 
    created_at DATETIME NOT NULL, 
    last_success_at DATETIME, 
    failure_count SMALLINT NOT NULL, 
    CONSTRAINT pk_push_subscriptions PRIMARY KEY (id), 
    CONSTRAINT fk_push_subscriptions_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT uq_push_subscriptions_endpoint_hash UNIQUE (endpoint_hash)
);

CREATE INDEX ix_push_subscriptions_user_id ON push_subscriptions (user_id);

CREATE TABLE report_category_translations (
    id INTEGER NOT NULL AUTO_INCREMENT, 
    category_id INTEGER NOT NULL, 
    locale VARCHAR(5) NOT NULL, 
    name VARCHAR(120) NOT NULL, 
    description VARCHAR(500), 
    CONSTRAINT pk_report_category_translations PRIMARY KEY (id), 
    CONSTRAINT fk_report_category_translations_category_id_report_categories FOREIGN KEY(category_id) REFERENCES report_categories (id) ON DELETE CASCADE, 
    CONSTRAINT uq_category_locale UNIQUE (category_id, locale)
);

CREATE TABLE reports (
    id INTEGER NOT NULL AUTO_INCREMENT, 
    reference VARCHAR(24), 
    title VARCHAR(160) NOT NULL, 
    description TEXT, 
    language VARCHAR(5) NOT NULL, 
    category_id INTEGER NOT NULL, 
    status_id INTEGER NOT NULL, 
    severity VARCHAR(8) NOT NULL, 
    km_marker NUMERIC(7, 2), 
    road_section_id INTEGER, 
    latitude NUMERIC(9, 6), 
    longitude NUMERIC(9, 6), 
    location_source VARCHAR(8) NOT NULL, 
    reporter_id INTEGER, 
    guest_name VARCHAR(120), 
    guest_phone VARCHAR(20), 
    assigned_team_id INTEGER, 
    assigned_user_id INTEGER, 
    first_response_at DATETIME, 
    resolved_at DATETIME, 
    points_awarded BOOL NOT NULL, 
    created_at DATETIME NOT NULL, 
    updated_at DATETIME NOT NULL, 
    CONSTRAINT pk_reports PRIMARY KEY (id), 
    CONSTRAINT ck_reports_severity_values CHECK (severity IN ('low','medium','high')), 
    CONSTRAINT ck_reports_km_positive CHECK (km_marker IS NULL OR km_marker >= 0), 
    CONSTRAINT ck_reports_lat_range CHECK (latitude IS NULL OR (latitude BETWEEN -90 AND 90)), 
    CONSTRAINT ck_reports_lng_range CHECK (longitude IS NULL OR (longitude BETWEEN -180 AND 180)), 
    CONSTRAINT fk_reports_assigned_team_id_teams FOREIGN KEY(assigned_team_id) REFERENCES teams (id) ON DELETE SET NULL, 
    CONSTRAINT fk_reports_assigned_user_id_users FOREIGN KEY(assigned_user_id) REFERENCES users (id) ON DELETE SET NULL, 
    CONSTRAINT fk_reports_category_id_report_categories FOREIGN KEY(category_id) REFERENCES report_categories (id), 
    CONSTRAINT fk_reports_reporter_id_users FOREIGN KEY(reporter_id) REFERENCES users (id) ON DELETE SET NULL, 
    CONSTRAINT fk_reports_road_section_id_road_sections FOREIGN KEY(road_section_id) REFERENCES road_sections (id) ON DELETE SET NULL, 
    CONSTRAINT fk_reports_status_id_report_statuses FOREIGN KEY(status_id) REFERENCES report_statuses (id), 
    CONSTRAINT uq_reports_reference UNIQUE (reference)
);

CREATE INDEX ix_reports_assigned_team_id ON reports (assigned_team_id);

CREATE INDEX ix_reports_assigned_user_id ON reports (assigned_user_id);

CREATE INDEX ix_reports_category_id ON reports (category_id);

CREATE INDEX ix_reports_created_at ON reports (created_at);

CREATE INDEX ix_reports_km_marker ON reports (km_marker);

CREATE INDEX ix_reports_reporter_id ON reports (reporter_id);

CREATE INDEX ix_reports_road_section_id ON reports (road_section_id);

CREATE INDEX ix_reports_section_km ON reports (road_section_id, km_marker);

CREATE INDEX ix_reports_severity ON reports (severity);

CREATE INDEX ix_reports_status_created ON reports (status_id, created_at);

CREATE INDEX ix_reports_status_id ON reports (status_id);

CREATE TABLE system_settings (
    id INTEGER NOT NULL AUTO_INCREMENT, 
    `key` VARCHAR(64) NOT NULL, 
    value TEXT, 
    value_type VARCHAR(8) NOT NULL, 
    is_public BOOL NOT NULL, 
    description VARCHAR(255), 
    updated_at DATETIME NOT NULL, 
    updated_by_id INTEGER, 
    CONSTRAINT pk_system_settings PRIMARY KEY (id), 
    CONSTRAINT fk_system_settings_updated_by_id_users FOREIGN KEY(updated_by_id) REFERENCES users (id) ON DELETE SET NULL, 
    CONSTRAINT uq_system_settings_key UNIQUE (`key`)
);

CREATE TABLE team_members (
    id INTEGER NOT NULL AUTO_INCREMENT, 
    team_id INTEGER NOT NULL, 
    user_id INTEGER NOT NULL, 
    is_leader BOOL NOT NULL, 
    joined_at DATETIME NOT NULL, 
    CONSTRAINT pk_team_members PRIMARY KEY (id), 
    CONSTRAINT fk_team_members_team_id_teams FOREIGN KEY(team_id) REFERENCES teams (id) ON DELETE CASCADE, 
    CONSTRAINT fk_team_members_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT uq_team_user UNIQUE (team_id, user_id)
);

CREATE INDEX ix_team_members_team_id ON team_members (team_id);

CREATE INDEX ix_team_members_user_id ON team_members (user_id);

CREATE TABLE user_roles (
    user_id INTEGER NOT NULL, 
    role_id INTEGER NOT NULL, 
    CONSTRAINT pk_user_roles PRIMARY KEY (user_id, role_id), 
    CONSTRAINT fk_user_roles_role_id_roles FOREIGN KEY(role_id) REFERENCES roles (id) ON DELETE CASCADE, 
    CONSTRAINT fk_user_roles_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE announcement_translations (
    id INTEGER NOT NULL AUTO_INCREMENT, 
    announcement_id INTEGER NOT NULL, 
    locale VARCHAR(5) NOT NULL, 
    title VARCHAR(200) NOT NULL, 
    body TEXT, 
    CONSTRAINT pk_announcement_translations PRIMARY KEY (id), 
    CONSTRAINT fk_announcement_translations_announcement_id_announcements FOREIGN KEY(announcement_id) REFERENCES announcements (id) ON DELETE CASCADE, 
    CONSTRAINT uq_announcement_locale UNIQUE (announcement_id, locale)
);

CREATE TABLE employee_assignments (
    id INTEGER NOT NULL AUTO_INCREMENT, 
    report_id INTEGER NOT NULL, 
    team_id INTEGER, 
    assignee_id INTEGER, 
    assigned_by_id INTEGER, 
    note VARCHAR(1000), 
    is_active BOOL NOT NULL, 
    assigned_at DATETIME NOT NULL, 
    completed_at DATETIME, 
    CONSTRAINT pk_employee_assignments PRIMARY KEY (id), 
    CONSTRAINT fk_employee_assignments_assigned_by_id_users FOREIGN KEY(assigned_by_id) REFERENCES users (id) ON DELETE SET NULL, 
    CONSTRAINT fk_employee_assignments_assignee_id_users FOREIGN KEY(assignee_id) REFERENCES users (id) ON DELETE SET NULL, 
    CONSTRAINT fk_employee_assignments_report_id_reports FOREIGN KEY(report_id) REFERENCES reports (id) ON DELETE CASCADE, 
    CONSTRAINT fk_employee_assignments_team_id_teams FOREIGN KEY(team_id) REFERENCES teams (id) ON DELETE SET NULL
);

CREATE INDEX ix_employee_assignments_assignee_id ON employee_assignments (assignee_id);

CREATE INDEX ix_employee_assignments_is_active ON employee_assignments (is_active);

CREATE INDEX ix_employee_assignments_report_id ON employee_assignments (report_id);

CREATE INDEX ix_employee_assignments_team_id ON employee_assignments (team_id);

CREATE TABLE notifications (
    id INTEGER NOT NULL AUTO_INCREMENT, 
    user_id INTEGER NOT NULL, 
    kind VARCHAR(24) NOT NULL, 
    title_ar VARCHAR(200) NOT NULL, 
    title_en VARCHAR(200) NOT NULL, 
    body_ar VARCHAR(1000), 
    body_en VARCHAR(1000), 
    url VARCHAR(255), 
    report_id INTEGER, 
    announcement_id INTEGER, 
    is_read BOOL NOT NULL, 
    read_at DATETIME, 
    created_at DATETIME NOT NULL, 
    CONSTRAINT pk_notifications PRIMARY KEY (id), 
    CONSTRAINT fk_notifications_announcement_id_announcements FOREIGN KEY(announcement_id) REFERENCES announcements (id) ON DELETE CASCADE, 
    CONSTRAINT fk_notifications_report_id_reports FOREIGN KEY(report_id) REFERENCES reports (id) ON DELETE CASCADE, 
    CONSTRAINT fk_notifications_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_notifications_created_at ON notifications (created_at);

CREATE INDEX ix_notifications_user_id ON notifications (user_id);

CREATE INDEX ix_notifications_user_read ON notifications (user_id, is_read);

CREATE TABLE points_transactions (
    id INTEGER NOT NULL AUTO_INCREMENT, 
    user_id INTEGER NOT NULL, 
    report_id INTEGER, 
    points INTEGER NOT NULL, 
    reason VARCHAR(32) NOT NULL, 
    created_at DATETIME NOT NULL, 
    CONSTRAINT pk_points_transactions PRIMARY KEY (id), 
    CONSTRAINT fk_points_transactions_report_id_reports FOREIGN KEY(report_id) REFERENCES reports (id) ON DELETE SET NULL, 
    CONSTRAINT fk_points_transactions_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT uq_points_once UNIQUE (user_id, report_id, reason)
);

CREATE INDEX ix_points_transactions_user_id ON points_transactions (user_id);

CREATE TABLE report_attachments (
    id INTEGER NOT NULL AUTO_INCREMENT, 
    report_id INTEGER NOT NULL, 
    stored_name VARCHAR(80) NOT NULL, 
    original_name VARCHAR(255), 
    mime_type VARCHAR(64) NOT NULL, 
    size_bytes INTEGER NOT NULL, 
    width INTEGER, 
    height INTEGER, 
    uploaded_by_id INTEGER, 
    created_at DATETIME NOT NULL, 
    CONSTRAINT pk_report_attachments PRIMARY KEY (id), 
    CONSTRAINT fk_report_attachments_report_id_reports FOREIGN KEY(report_id) REFERENCES reports (id) ON DELETE CASCADE, 
    CONSTRAINT fk_report_attachments_uploaded_by_id_users FOREIGN KEY(uploaded_by_id) REFERENCES users (id) ON DELETE SET NULL, 
    CONSTRAINT uq_report_attachments_stored_name UNIQUE (stored_name)
);

CREATE INDEX ix_report_attachments_report_id ON report_attachments (report_id);

CREATE TABLE report_notes (
    id INTEGER NOT NULL AUTO_INCREMENT, 
    report_id INTEGER NOT NULL, 
    author_id INTEGER, 
    body TEXT NOT NULL, 
    is_internal BOOL NOT NULL, 
    created_at DATETIME NOT NULL, 
    CONSTRAINT pk_report_notes PRIMARY KEY (id), 
    CONSTRAINT fk_report_notes_author_id_users FOREIGN KEY(author_id) REFERENCES users (id) ON DELETE SET NULL, 
    CONSTRAINT fk_report_notes_report_id_reports FOREIGN KEY(report_id) REFERENCES reports (id) ON DELETE CASCADE
);

CREATE INDEX ix_report_notes_report_id ON report_notes (report_id);

CREATE TABLE report_status_history (
    id INTEGER NOT NULL AUTO_INCREMENT, 
    report_id INTEGER NOT NULL, 
    from_status_id INTEGER, 
    to_status_id INTEGER NOT NULL, 
    changed_by_id INTEGER, 
    public_note VARCHAR(1000), 
    internal_note VARCHAR(2000), 
    created_at DATETIME NOT NULL, 
    CONSTRAINT pk_report_status_history PRIMARY KEY (id), 
    CONSTRAINT fk_report_status_history_changed_by_id_users FOREIGN KEY(changed_by_id) REFERENCES users (id) ON DELETE SET NULL, 
    CONSTRAINT fk_report_status_history_from_status_id_report_statuses FOREIGN KEY(from_status_id) REFERENCES report_statuses (id), 
    CONSTRAINT fk_report_status_history_report_id_reports FOREIGN KEY(report_id) REFERENCES reports (id) ON DELETE CASCADE, 
    CONSTRAINT fk_report_status_history_to_status_id_report_statuses FOREIGN KEY(to_status_id) REFERENCES report_statuses (id)
);

CREATE INDEX ix_report_status_history_created_at ON report_status_history (created_at);

CREATE INDEX ix_report_status_history_report_id ON report_status_history (report_id);

INSERT INTO alembic_version (version_num) VALUES ('6818f5288d1c');

