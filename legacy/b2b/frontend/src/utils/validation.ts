import { z } from 'zod';

/**
 * Common Zod schemas used across forms.
 */

export const loginSchema = z.object({
  email: z
    .string()
    .min(1, 'auth.emailLabel')
    .max(254),
  password: z
    .string()
    .min(1, 'auth.passwordLabel')
    .max(128),
});

export type LoginFormData = z.infer<typeof loginSchema>;

export const kycRegistrationSchema = z.object({
  companyName: z.string().min(2).max(255),
  inn: z.string().min(9).max(14),
  contactEmail: z.string().email(),
  contactPhone: z.string().min(7).max(20),
  contactPerson: z.string().min(2).max(128),
});

export type KYCRegistrationFormData = z.infer<typeof kycRegistrationSchema>;

/**
 * Simple resolver for react-hook-form + zod without @hookform/resolvers.
 * If you install @hookform/resolvers, replace this with zodResolver import.
 */
export function zodResolver<T extends z.ZodType>(schema: T) {
  return async (data: unknown) => {
    const result = schema.safeParse(data);
    if (result.success) {
      return { values: result.data as z.infer<T>, errors: {} };
    }

    const errors: Record<string, { type: string; message: string }> = {};
    for (const issue of result.error.issues) {
      const path = issue.path.join('.');
      if (!errors[path]) {
        errors[path] = {
          type: issue.code,
          message: issue.message,
        };
      }
    }
    return { values: {}, errors };
  };
}
