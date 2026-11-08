import SwiftUI

/// Edit everything the dashboard shows about your car. Changes apply when you tap Save.
struct CarProfileEditor: View {
    let store: CarProfileStore
    let history: JobHistory

    @Environment(\.dismiss) private var dismiss
    @State private var draft: CarProfile
    @State private var isConfirmingClear = false

    init(store: CarProfileStore, history: JobHistory) {
        self.store = store
        self.history = history
        _draft = State(initialValue: store.profile)
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Your car") {
                    LabeledContent("Model", value: "2022 Subaru WRX")
                    TextField("Trim, like Premium", text: $draft.trim)
                    TextField("Color", text: $draft.color)
                    TextField("License plate", text: $draft.plate)
                        .textInputAutocapitalization(.characters)
                    TextField("VIN", text: $draft.vin)
                        .textInputAutocapitalization(.characters)
                        .autocorrectionDisabled()
                }

                Section("Odometer") {
                    NumberField(title: "Miles", value: Binding(
                        get: { draft.odometer },
                        set: {
                            draft.odometer = $0
                            draft.odometerUpdated = .now
                        }
                    ), unit: "mi")
                }

                Section {
                    ForEach($draft.maintenance) { $item in
                        NavigationLink {
                            MaintenanceItemEditor(item: $item)
                        } label: {
                            Label(item.name.isEmpty ? "Untitled" : item.name, systemImage: item.symbol)
                        }
                        .deleteDisabled(item.isOilChange)
                    }
                    .onDelete { draft.maintenance.remove(atOffsets: $0) }

                    Button {
                        draft.maintenance.append(MaintenanceItem(name: "New item"))
                    } label: {
                        Label("Add maintenance item", systemImage: "plus.circle.fill")
                    }
                } header: {
                    Text("Maintenance")
                } footer: {
                    Text("These intervals are your own settings. Use the schedule in your owner's manual.")
                }

                Section {
                    ForEach($draft.details) { $detail in
                        HStack {
                            TextField("Label", text: $detail.label)
                                .foregroundStyle(Theme.inkSecondary)
                            TextField("Value", text: $detail.value)
                                .multilineTextAlignment(.trailing)
                        }
                    }
                    .onDelete { draft.details.remove(atOffsets: $0) }

                    Button {
                        draft.details.append(CarDetail(label: "", value: ""))
                    } label: {
                        Label("Add a spec", systemImage: "plus.circle.fill")
                    }
                } header: {
                    Text("Your specs")
                } footer: {
                    Text("Anything you want on the dashboard, like tire pressure or your oil type.")
                }

                Section {
                    Button("Clear service history", role: .destructive) {
                        isConfirmingClear = true
                    }
                    .disabled(history.records.isEmpty)
                }
            }
            .navigationTitle("Your car")
            .navigationBarTitleDisplayMode(.inline)
            .scrollDismissesKeyboard(.interactively)
            .toolbar {
                ToolbarItemGroup(placement: .keyboard) {
                    Spacer()
                    Button("Done") { hideKeyboard() }
                        .fontWeight(.semibold)
                }
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        draft.details.removeAll { $0.label.isEmpty && $0.value.isEmpty }
                        store.profile = draft
                        dismiss()
                    }
                    .fontWeight(.semibold)
                }
            }
            .confirmationDialog("Clear every finished job from your service history?",
                                isPresented: $isConfirmingClear, titleVisibility: .visible) {
                Button("Clear history", role: .destructive) { history.clear() }
            }
        }
        .tint(Theme.accent)
    }
}

/// One maintenance item: its name, icon, interval, and when you last did it.
private struct MaintenanceItemEditor: View {
    @Binding var item: MaintenanceItem

    private static let symbols = [
        "drop.fill", "circle.circle", "wind", "windshield.front.and.wiper",
        "car.fill", "battery.100percent", "thermometer.medium", "wrench.and.screwdriver.fill",
        "fan.fill", "bolt.car.fill", "gearshape.fill", "lightbulb.fill",
    ]

    var body: some View {
        Form {
            Section("Name") {
                TextField("Name", text: $item.name)
                    .disabled(item.isOilChange)
            }

            Section("Icon") {
                LazyVGrid(columns: Array(repeating: GridItem(.flexible()), count: 6), spacing: 12) {
                    ForEach(Self.symbols, id: \.self) { symbol in
                        Button {
                            item.symbol = symbol
                        } label: {
                            Image(systemName: symbol)
                                .font(.title3)
                                .frame(width: 44, height: 44)
                                .foregroundStyle(item.symbol == symbol ? .white : Theme.ink)
                                .background(item.symbol == symbol ? Theme.accent : Theme.pearl, in: Circle())
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel(symbol)
                        .accessibilityAddTraits(item.symbol == symbol ? .isSelected : [])
                    }
                }
                .padding(.vertical, 4)
            }

            Section {
                NumberField(title: "Every", value: $item.intervalMiles, unit: "mi")
                NumberField(title: "Or every", value: $item.intervalMonths, unit: "months")
            } header: {
                Text("Interval")
            } footer: {
                Text("Whichever comes first. Leave one empty to use only the other.")
            }

            Section("Last done") {
                NumberField(title: "At", value: $item.lastMiles, unit: "mi")
                Toggle("Date", isOn: Binding(
                    get: { item.lastDate != nil },
                    set: { item.lastDate = $0 ? (item.lastDate ?? .now) : nil }
                ))
                if let date = item.lastDate {
                    DatePicker("On", selection: Binding(get: { date }, set: { item.lastDate = $0 }),
                               in: ...Date.now, displayedComponents: .date)
                }
            }
        }
        .navigationTitle(item.name.isEmpty ? "Item" : item.name)
        .navigationBarTitleDisplayMode(.inline)
        .scrollDismissesKeyboard(.interactively)
        .toolbar {
            ToolbarItemGroup(placement: .keyboard) {
                Spacer()
                Button("Done") { hideKeyboard() }
                    .fontWeight(.semibold)
            }
        }
    }
}

/// A number you type, with its unit after it. Empty means "not set".
private struct NumberField: View {
    let title: String
    @Binding var value: Int?
    let unit: String

    init(title: String, value: Binding<Int?>, unit: String) {
        self.title = title
        self._value = value
        self.unit = unit
    }

    init(title: String, value: Binding<Int>, unit: String) {
        self.init(title: title, value: Binding<Int?>(
            get: { value.wrappedValue },
            set: { value.wrappedValue = $0 ?? 0 }
        ), unit: unit)
    }

    var body: some View {
        HStack {
            Text(title)
            Spacer()
            TextField("Not set", text: Binding(
                get: { value.map { String($0) } ?? "" },
                set: { value = Int($0.filter(\.isNumber)) }
            ))
            .keyboardType(.numberPad)
            .multilineTextAlignment(.trailing)
            .monospacedDigit()
            .frame(maxWidth: 140)
            Text(unit)
                .foregroundStyle(Theme.inkSecondary)
        }
    }
}

/// Quick odometer update from the dashboard tile.
struct OdometerSheet: View {
    let current: Int
    let onSave: (Int) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var text = ""
    @FocusState private var isFocused: Bool

    private var miles: Int? { Int(text.filter(\.isNumber)) }

    private func save() {
        if let miles { onSave(miles) }
        dismiss()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("Update odometer")
                .font(.title2.weight(.semibold))
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                TextField(current.formatted(), text: $text)
                    .font(Theme.number(56))
                    .tracking(-1.5)
                    .keyboardType(.numberPad)
                    .monospacedDigit()
                    .focused($isFocused)
                Text("mi")
                    .font(.title2)
                    .foregroundStyle(Theme.inkSecondary)
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 8)
            .background(Theme.pearl, in: RoundedRectangle(cornerRadius: Theme.Radius.small, style: .continuous))

            if let miles, miles < current {
                Label("That's lower than the last reading (\(current.formatted()) mi).", systemImage: "exclamationmark.triangle.fill")
                    .font(.subheadline)
                    .foregroundStyle(Theme.warning)
            }

            Spacer(minLength: 0)

            Button(action: save) {
                Text("Save")
                    .font(Theme.buttonFont)
                    .frame(maxWidth: .infinity, minHeight: Theme.buttonHeight)
            }
            .carvisButton(prominent: true)
            .disabled(miles == nil)
        }
        .padding(24)
        // The number pad has no return key, so Save also rides on top of the keyboard.
        .toolbar {
            ToolbarItemGroup(placement: .keyboard) {
                Button("Cancel") { dismiss() }
                Spacer()
                Button("Save") { save() }
                    .fontWeight(.semibold)
                    .disabled(miles == nil)
            }
        }
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
        .onAppear { isFocused = true }
    }
}

/// Closes the keyboard from a toolbar button.
@MainActor
func hideKeyboard() {
    UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil)
}
